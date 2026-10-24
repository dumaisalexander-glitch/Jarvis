package com.loryzon.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.ToneGenerator
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.max
import kotlin.math.sqrt

/**
 * Le cœur de Jarvis sur le téléphone. Tourne en service au premier plan pour continuer
 * d'écouter même écran éteint :
 * attente du mot d'éveil -> écoute (arrêt automatique au silence) -> serveur -> réponse vocale
 * -> réécoute (mode conversation) ou retour à l'attente.
 */
class JarvisService : Service() {

    private lateinit var config: Config
    private lateinit var api: ApiClient
    private val main = Handler(Looper.getMainLooper())
    private val network = Executors.newSingleThreadExecutor()
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    @Volatile private var detector: WakeWordDetector? = null
    private val detectorLock = Any()
    private var tone: ToneGenerator? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var focusRequest: AudioFocusRequest? = null

    @Volatile private var running = false
    @Volatile private var micPaused = false   // micro libéré pour la reconnaissance Google
    private var recognizer: SpeechRecognizer? = null
    private var googleMode = false
    @Volatile private var phase = Phase.OFF
    private var audioThread: Thread? = null

    // Session de conversation (un résumé Teams par session)
    private var sessionId = newSessionId()
    private var sessionTurns = 0
    private val sessionTimeout = Runnable { endSession(spoken = false) }

    // Enregistrement en cours
    private var rec = ShortArray(SAMPLE_RATE * MAX_RECORD_SEC)
    @Volatile private var recLen = 0
    @Volatile private var speechHeard = false
    private var silentSamples = 0
    private var listenedSamples = 0
    private var noiseFloor = 300.0
    private var cooldownUntil = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        config = Config(this)
        api = ApiClient(config)
        createChannel()
        startInForeground()
        tone = try { ToneGenerator(AudioManager.STREAM_MUSIC, 70) } catch (e: Exception) { null }
        tts = TextToSpeech(this) { status -> onTtsInit(status) }
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:ecoute").apply { setReferenceCounted(false); acquire() }
        loadDetector()
        startAudio()
    }

    private fun onTtsInit(status: Int) {
        val t = tts
        if (status == TextToSpeech.SUCCESS && t != null) {
            val r = t.setLanguage(Locale.CANADA_FRENCH)
            if (r == TextToSpeech.LANG_MISSING_DATA || r == TextToSpeech.LANG_NOT_SUPPORTED) t.setLanguage(Locale.FRENCH)
            t.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            t.setOnUtteranceProgressListener(ttsListener)
            ttsReady = true
        } else {
            JarvisBus.update { it.copy(message = "La voix de synthèse n'est pas disponible sur ce téléphone.") }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TALK -> main.post {
                when (phase) {
                    Phase.LISTENING -> if (googleMode) recognizer?.stopListening() else finishListening()
                    Phase.SPEAKING -> { tts?.stop(); startListening() }
                    Phase.THINKING -> Unit
                    else -> startListening()
                }
            }
            ACTION_END_SESSION -> main.post { endSession(spoken = true) }
            ACTION_RELOAD -> main.post { loadDetector(); goIdle() }
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        audioThread?.join(1000)
        main.removeCallbacksAndMessages(null)
        if (sessionTurns > 0) {
            val id = sessionId
            network.execute { runCatching { api.endSession(id) } }
        }
        network.shutdown()
        stopRecognizer()
        tts?.shutdown()
        tone?.release()
        synchronized(detectorLock) { detector?.close(); detector = null }
        abandonFocus()
        wakeLock?.let { if (it.isHeld) it.release() }
        JarvisBus.update { it.copy(phase = Phase.OFF, level = 0f) }
        super.onDestroy()
    }

    // ------------------------------------------------------------------ audio

    private fun loadDetector() {
        synchronized(detectorLock) {
            detector?.close()
            detector = null
        }
        if (!config.wakeWord) return
        try {
            val d = WakeWordDetector(this)
            synchronized(detectorLock) { detector = d }
        } catch (e: Throwable) {
            Log.e(TAG, "mot d'éveil", e)
            JarvisBus.update { it.copy(message = "Mot d'éveil indisponible : ${e.message}") }
        }
    }

    @SuppressLint("MissingPermission")
    private fun startAudio() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            JarvisBus.update { it.copy(message = "Jarvis a besoin de la permission du micro.") }
            stopSelf()
            return
        }
        running = true
        goIdle()
        audioThread = Thread({
            val buf = ShortArray(FRAME)
            var record: AudioRecord? = null
            try {
                while (running) {
                    if (micPaused) {
                        record?.let { it.stop(); it.release() }
                        record = null
                        Thread.sleep(30)
                        continue
                    }
                    if (record == null) {
                        record = openRecord()
                        if (record == null) {
                            JarvisBus.update { it.copy(message = "Impossible d'ouvrir le micro.") }
                            Thread.sleep(1000)
                            continue
                        }
                        record.startRecording()
                    }
                    val n = record.read(buf, 0, FRAME)
                    if (n > 0) onAudio(buf, n)
                }
            } catch (e: InterruptedException) {
                // arrêt du service
            } finally {
                record?.let { it.stop(); it.release() }
            }
        }, "jarvis-audio").apply { priority = Thread.MAX_PRIORITY; start() }
    }

    @SuppressLint("MissingPermission")
    private fun openRecord(): AudioRecord? {
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val r = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(minBuf, FRAME * 8),
        )
        if (r.state != AudioRecord.STATE_INITIALIZED) {
            r.release()
            return null
        }
        return r
    }

    /** Appelé sur le fil audio toutes les 40 ms. */
    private fun onAudio(buf: ShortArray, n: Int) {
        val level = rms(buf, n)
        when (phase) {
            Phase.IDLE, Phase.IDLE_NO_WAKE -> {
                noiseFloor = noiseFloor * 0.98 + level * 0.02
                val score = synchronized(detectorLock) {
                    val d = detector ?: return
                    try { d.process(buf, n) } catch (e: Throwable) { 0f }
                }
                if (score >= config.threshold && System.currentTimeMillis() > cooldownUntil) {
                    cooldownUntil = System.currentTimeMillis() + 2000
                    main.post { if (phase == Phase.IDLE) startListening() }
                }
            }
            Phase.LISTENING -> {
                if (googleMode) return
                JarvisBus.update { it.copy(level = (level / 4000.0).coerceIn(0.0, 1.0).toFloat()) }
                listenedSamples += n
                if (listenedSamples < SAMPLE_RATE * 3 / 10) return // ignore le bip de départ
                if (recLen + n <= rec.size) {
                    System.arraycopy(buf, 0, rec, recLen, n)
                    recLen += n
                }
                val speechThreshold = max(noiseFloor * 2.5, 450.0)
                if (level > speechThreshold) {
                    speechHeard = true
                    silentSamples = 0
                } else {
                    silentSamples += n
                }
                val done = (speechHeard && silentSamples > SAMPLE_RATE * END_SILENCE_MS / 1000) ||
                    (!speechHeard && listenedSamples > SAMPLE_RATE * NO_SPEECH_SEC) ||
                    recLen + n > rec.size
                if (done) main.post { if (phase == Phase.LISTENING) finishListening() }
            }
            else -> Unit
        }
    }

    private fun rms(buf: ShortArray, n: Int): Double {
        var sum = 0.0
        for (i in 0 until n) sum += buf[i].toDouble() * buf[i]
        return sqrt(sum / max(n, 1))
    }

    // ------------------------------------------------------------- états

    private fun goIdle() {
        stopRecognizer()
        micPaused = false
        abandonFocus()
        synchronized(detectorLock) { detector?.reset() }
        setPhase(if (detector != null) Phase.IDLE else Phase.IDLE_NO_WAKE)
    }

    private fun startListening() {
        if (!config.isConfigured) {
            say("Je ne suis pas encore configuré. Ouvre les réglages pour entrer l'adresse du serveur.")
            return
        }
        main.removeCallbacks(sessionTimeout)
        requestFocus()
        if (config.stt == Config.STT_GOOGLE && SpeechRecognizer.isRecognitionAvailable(this)) {
            startGoogle()
            return
        }
        googleMode = false
        micPaused = false
        recLen = 0
        speechHeard = false
        silentSamples = 0
        listenedSamples = 0
        tone?.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
        setPhase(Phase.LISTENING)
    }

    private fun finishListening() {
        if (!speechHeard || recLen < SAMPLE_RATE / 2) {
            tone?.startTone(ToneGenerator.TONE_PROP_NACK, 120)
            JarvisBus.update { it.copy(level = 0f) }
            goIdle()
            scheduleTimeout()
            return
        }
        tone?.startTone(ToneGenerator.TONE_PROP_ACK, 100)
        setPhase(Phase.THINKING)
        val audio = rec.copyOf(recLen)
        val id = sessionId
        network.execute {
            try {
                val r = api.converse(audio, audio.size, id)
                main.post { onReply(r) }
            } catch (e: Exception) {
                Log.e(TAG, "converse", e)
                main.post {
                    JarvisBus.update { it.copy(message = e.message ?: "Erreur réseau") }
                    speakThen("Désolé, je n'arrive pas à joindre le serveur.", listenAfter = false)
                }
            }
        }
    }

    // ------------------------------------------------------------- reconnaissance Google

    private fun startGoogle() {
        googleMode = true
        micPaused = true // libère le micro pour Google
        setPhase(Phase.LISTENING)
        tone?.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
        main.postDelayed({
            if (phase != Phase.LISTENING || !googleMode) return@postDelayed
            stopRecognizer()
            val rec = SpeechRecognizer.createSpeechRecognizer(this)
            recognizer = rec
            rec.setRecognitionListener(googleListener)
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fr-CA")
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2000L)
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1500L)
            }
            try {
                rec.startListening(intent)
            } catch (e: Exception) {
                Log.e(TAG, "google", e)
                JarvisBus.update { it.copy(message = "Reconnaissance Google indisponible : ${e.message}") }
                goIdle()
            }
        }, 250) // le temps que notre micro soit libéré et que le bip finisse
    }

    private fun stopRecognizer() {
        recognizer?.let {
            try { it.cancel(); it.destroy() } catch (e: Exception) { }
        }
        recognizer = null
    }

    private val googleListener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {
            JarvisBus.update { it.copy(level = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)) }
        }
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}
        override fun onPartialResults(partialResults: Bundle?) {
            val t = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
            if (!t.isNullOrBlank()) JarvisBus.update { it.copy(transcript = t) }
        }
        override fun onEvent(eventType: Int, params: Bundle?) {}
        override fun onResults(results: Bundle?) {
            val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim().orEmpty()
            main.post {
                if (phase != Phase.LISTENING) return@post
                stopRecognizer()
                googleMode = false
                if (text.length < 2) {
                    tone?.startTone(ToneGenerator.TONE_PROP_NACK, 120)
                    goIdle()
                    scheduleTimeout()
                } else {
                    tone?.startTone(ToneGenerator.TONE_PROP_ACK, 100)
                    sendText(text)
                }
            }
        }
        override fun onError(error: Int) {
            main.post {
                if (phase != Phase.LISTENING) return@post
                googleMode = false
                val quiet = error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                if (!quiet) {
                    JarvisBus.update { it.copy(message = "Reconnaissance vocale : erreur $error" +
                        if (error == SpeechRecognizer.ERROR_NETWORK || error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT) " (pas de réseau)" else "") }
                }
                tone?.startTone(ToneGenerator.TONE_PROP_NACK, 120)
                goIdle()
                scheduleTimeout()
            }
        }
    }

    private fun sendText(text: String) {
        micPaused = false
        JarvisBus.update { it.copy(transcript = text, level = 0f) }
        setPhase(Phase.THINKING)
        val id = sessionId
        network.execute {
            try {
                val r = api.converseText(text, id)
                main.post { onReply(r) }
            } catch (e: Exception) {
                Log.e(TAG, "converse", e)
                main.post {
                    JarvisBus.update { it.copy(message = e.message ?: "Erreur réseau") }
                    speakThen("Désolé, je n'arrive pas à joindre le serveur.", listenAfter = false)
                }
            }
        }
    }

    private fun onReply(r: ApiClient.Reply) {
        sessionTurns++
        JarvisBus.update {
            it.copy(transcript = r.transcription, reply = r.reponse, changes = r.changements, message = "", level = 0f)
        }
        if (r.finSession) {
            sessionId = newSessionId()
            sessionTurns = 0
            speakThen(r.reponse, listenAfter = false)
        } else {
            speakThen(r.reponse, listenAfter = config.conversation)
        }
    }

    private var listenAfterSpeech = false

    private fun speakThen(text: String, listenAfter: Boolean) {
        listenAfterSpeech = listenAfter
        val t = tts
        if (t == null || !ttsReady) {
            afterSpeech()
            return
        }
        setPhase(Phase.SPEAKING)
        requestFocus()
        t.speak(text, TextToSpeech.QUEUE_FLUSH, null, "r" + System.currentTimeMillis())
    }

    private val ttsListener = object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String?) {}
        override fun onDone(utteranceId: String?) { main.post { if (phase == Phase.SPEAKING) afterSpeech() } }
        @Deprecated("Deprecated in Java")
        override fun onError(utteranceId: String?) { main.post { if (phase == Phase.SPEAKING) afterSpeech() } }
        override fun onStop(utteranceId: String?, interrupted: Boolean) {}
    }

    private fun afterSpeech() {
        if (listenAfterSpeech) {
            // petite pause pour que l'écho de la voix ne soit pas enregistré
            main.postDelayed({ if (phase == Phase.SPEAKING || phase == Phase.THINKING) startListening() }, 350)
            setPhase(Phase.THINKING)
        } else {
            goIdle()
        }
        scheduleTimeout()
    }

    private fun say(text: String) {
        JarvisBus.update { it.copy(message = text) }
        if (ttsReady) speakThen(text, listenAfter = false)
    }

    // ------------------------------------------------------------- session

    private fun scheduleTimeout() {
        main.removeCallbacks(sessionTimeout)
        if (sessionTurns > 0) main.postDelayed(sessionTimeout, config.sessionTimeoutMin * 60_000L)
    }

    private fun endSession(spoken: Boolean) {
        main.removeCallbacks(sessionTimeout)
        if (sessionTurns == 0) {
            if (spoken) say("Il n'y a rien à résumer pour l'instant.")
            return
        }
        val id = sessionId
        sessionId = newSessionId()
        sessionTurns = 0
        network.execute {
            val msg = try { api.endSession(id) } catch (e: Exception) { "Résumé impossible : ${e.message}" }
            main.post {
                JarvisBus.update { it.copy(message = msg) }
                if (spoken && phase != Phase.LISTENING && phase != Phase.THINKING) say(msg)
            }
        }
    }

    // ------------------------------------------------------------- utilitaires

    private fun setPhase(p: Phase) {
        phase = p
        JarvisBus.update { it.copy(phase = p, level = if (p == Phase.LISTENING) it.level else 0f) }
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, notification(p.label))
    }

    private fun requestFocus() {
        if (focusRequest != null) return
        val am = getSystemService(AudioManager::class.java)
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
            ).build()
        am.requestAudioFocus(req)
        focusRequest = req
    }

    private fun abandonFocus() {
        focusRequest?.let { getSystemService(AudioManager::class.java).abandonAudioFocusRequest(it) }
        focusRequest = null
    }

    private fun createChannel() {
        val ch = NotificationChannel(CHANNEL, "Jarvis", NotificationManager.IMPORTANCE_LOW)
        ch.description = "Jarvis écoute en arrière-plan"
        getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
    }

    private fun startInForeground() {
        val n = notification("Démarrage…")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    private fun notification(text: String): Notification {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        fun action(a: String, req: Int) = PendingIntent.getService(this, req, Intent(this, JarvisService::class.java).setAction(a), flags)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle("Jarvis")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Parler", action(ACTION_TALK, 1)).build())
            .addAction(Notification.Action.Builder(null, "Terminer la session", action(ACTION_END_SESSION, 2)).build())
            .addAction(Notification.Action.Builder(null, "Arrêter", action(ACTION_STOP, 3)).build())
            .build()
    }

    companion object {
        private const val TAG = "Jarvis"
        const val ACTION_TALK = "com.loryzon.jarvis.TALK"
        const val ACTION_END_SESSION = "com.loryzon.jarvis.END_SESSION"
        const val ACTION_RELOAD = "com.loryzon.jarvis.RELOAD"
        const val ACTION_STOP = "com.loryzon.jarvis.STOP"
        private const val CHANNEL = "jarvis"
        private const val NOTIF_ID = 1
        const val SAMPLE_RATE = 16000
        private const val FRAME = 640            // 40 ms
        private const val MAX_RECORD_SEC = 60
        private const val END_SILENCE_MS = 1500
        private const val NO_SPEECH_SEC = 7

        private fun newSessionId() = "and_" + System.currentTimeMillis().toString(36)

        fun send(context: Context, action: String? = null) {
            val i = Intent(context, JarvisService::class.java)
            if (action != null) i.action = action
            context.startForegroundService(i)
        }
    }
}
