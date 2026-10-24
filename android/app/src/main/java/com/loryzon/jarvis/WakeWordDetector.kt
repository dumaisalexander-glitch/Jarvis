package com.loryzon.jarvis

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.nio.FloatBuffer
import kotlin.random.Random

/**
 * Détecteur de mot d'éveil (modèles openWakeWord en ONNX).
 * Même pipeline que desktop/wakeword.py, vérifié contre la version officielle :
 * blocs de 1280 échantillons (80 ms) -> mel (x/10 + 2) -> 76 trames -> embedding (96)
 * -> 16 derniers embeddings -> score du mot (0 à 1).
 */
class WakeWordDetector(context: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val opts = OrtSession.SessionOptions().apply { setIntraOpNumThreads(1); setInterOpNumThreads(1) }
    private val mel = load(context, "melspectrogram.onnx")
    private val emb = load(context, "embedding_model.onnx")
    private val word = load(context, "wakeword.onnx")
    private val melIn = mel.inputNames.first()
    private val embIn = emb.inputNames.first()
    private val wordIn = word.inputNames.first()

    private val pending = ShortArray(CHUNK)
    private var pendingCount = 0
    private val history = ShortArray(MEL_CONTEXT)
    private val mels = ArrayDeque<FloatArray>()      // trames de 32
    private val features = ArrayDeque<FloatArray>()  // embeddings de 96
    private var chunksSeen = 0

    init { reset() }

    private fun load(context: Context, name: String): OrtSession {
        val bytes = context.assets.open(name).use { it.readBytes() }
        return env.createSession(bytes, opts)
    }

    fun reset() {
        pendingCount = 0
        history.fill(0)
        mels.clear()
        repeat(MEL_WINDOW) { mels.addLast(FloatArray(32) { 1f }) }
        features.clear()
        val noise = ShortArray(16000 * 4) { Random.nextInt(-1000, 1000).toShort() }
        val spec = melspec(noise)
        var i = 0
        while (i + MEL_WINDOW <= spec.size) {
            features.addLast(embed(spec.subList(i, i + MEL_WINDOW)))
            i += 8
        }
        chunksSeen = 0
    }

    /** Ajoute de l'audio 16 kHz mono. Retourne le meilleur score vu. */
    fun process(pcm: ShortArray, length: Int = pcm.size): Float {
        var best = 0f
        var offset = 0
        while (offset < length) {
            val n = minOf(CHUNK - pendingCount, length - offset)
            System.arraycopy(pcm, offset, pending, pendingCount, n)
            pendingCount += n
            offset += n
            if (pendingCount == CHUNK) {
                best = maxOf(best, processChunk(pending))
                pendingCount = 0
            }
        }
        return best
    }

    private fun processChunk(chunk: ShortArray): Float {
        val audio = ShortArray(MEL_CONTEXT + CHUNK)
        System.arraycopy(history, 0, audio, 0, MEL_CONTEXT)
        System.arraycopy(chunk, 0, audio, MEL_CONTEXT, CHUNK)
        System.arraycopy(audio, audio.size - MEL_CONTEXT, history, 0, MEL_CONTEXT)

        for (frame in melspec(audio)) mels.addLast(frame)
        while (mels.size > 970) mels.removeFirst()

        features.addLast(embed(mels.subList(mels.size - MEL_WINDOW, mels.size)))
        while (features.size > 120) features.removeFirst()

        chunksSeen++
        if (chunksSeen < 5) return 0f
        return score()
    }

    private fun melspec(audio: ShortArray): List<FloatArray> {
        val input = FloatArray(audio.size) { audio[it].toFloat() }
        val flat = run(mel, melIn, input, longArrayOf(1, audio.size.toLong()))
        val frames = flat.size / 32
        return List(frames) { f -> FloatArray(32) { k -> flat[f * 32 + k] / 10f + 2f } }
    }

    private fun embed(window: List<FloatArray>): FloatArray {
        val input = FloatArray(MEL_WINDOW * 32)
        window.forEachIndexed { i, frame -> System.arraycopy(frame, 0, input, i * 32, 32) }
        return run(emb, embIn, input, longArrayOf(1, MEL_WINDOW.toLong(), 32, 1))
    }

    private fun score(): Float {
        val input = FloatArray(N_FEATURES * 96)
        val start = features.size - N_FEATURES
        for (i in 0 until N_FEATURES) System.arraycopy(features[start + i], 0, input, i * 96, 96)
        return run(word, wordIn, input, longArrayOf(1, N_FEATURES.toLong(), 96))[0]
    }

    private fun run(session: OrtSession, inputName: String, data: FloatArray, shape: LongArray): FloatArray {
        OnnxTensor.createTensor(env, FloatBuffer.wrap(data), shape).use { tensor ->
            session.run(mapOf(inputName to tensor)).use { result ->
                val out = (result.get(0) as OnnxTensor).floatBuffer
                val arr = FloatArray(out.remaining())
                out.get(arr)
                return arr
            }
        }
    }

    override fun close() {
        mel.close(); emb.close(); word.close(); opts.close()
    }

    companion object {
        const val CHUNK = 1280
        const val MEL_CONTEXT = 160 * 3
        const val MEL_WINDOW = 76
        const val N_FEATURES = 16
    }
}
