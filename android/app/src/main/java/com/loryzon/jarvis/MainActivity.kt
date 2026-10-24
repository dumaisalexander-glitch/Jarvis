package com.loryzon.jarvis

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {

    private lateinit var config: Config
    private lateinit var orb: OrbView
    private lateinit var status: TextView
    private lateinit var transcript: TextView
    private lateinit var reply: TextView
    private lateinit var changes: TextView
    private lateinit var message: TextView
    private lateinit var startStop: Button

    private val listener: (JarvisBus.Snapshot) -> Unit = { s -> show(s) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        config = Config(this)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(buildUi())
    }

    override fun onStart() {
        super.onStart()
        JarvisBus.listen(listener)
        if (!config.isConfigured) {
            startActivity(Intent(this, SettingsActivity::class.java))
            return
        }
        ensurePermissionsThenStart()
    }

    override fun onStop() {
        JarvisBus.unlisten(listener)
        super.onStop()
    }

    private fun ensurePermissionsThenStart() {
        val needed = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.RECORD_AUDIO
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            needed += Manifest.permission.POST_NOTIFICATIONS
        }
        if (needed.isEmpty()) {
            if (JarvisBus.state.phase == Phase.OFF) JarvisService.send(this)
        } else {
            requestPermissions(needed.toTypedArray(), 42)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            JarvisService.send(this)
        } else {
            message.text = "Sans le micro, Jarvis ne peut pas t'entendre. Autorise-le dans les paramètres Android."
        }
    }

    private fun show(s: JarvisBus.Snapshot) {
        orb.phase = s.phase
        orb.level = s.level
        status.text = s.phase.label
        transcript.text = if (s.transcript.isNotEmpty()) "Toi : ${s.transcript}" else ""
        reply.text = s.reply
        changes.text = s.changes.joinToString("\n") { "✔ $it" }
        changes.visibility = if (s.changes.isEmpty()) View.GONE else View.VISIBLE
        message.text = s.message
        message.visibility = if (s.message.isEmpty()) View.GONE else View.VISIBLE
        startStop.text = if (s.phase == Phase.OFF) "Démarrer Jarvis" else "Arrêter Jarvis"
    }

    // ------------------------------------------------------------- interface

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(11, 18, 24))
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }

        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        top.addView(TextView(this).apply {
            text = "JARVIS"
            setTextColor(Color.rgb(155, 234, 251))
            textSize = 20f
            typeface = Typeface.DEFAULT_BOLD
            letterSpacing = 0.2f
        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        top.addView(smallButton("Projets") { openProjects() })
        top.addView(smallButton("Réglages") { startActivity(Intent(this, SettingsActivity::class.java)) })
        root.addView(top)

        orb = OrbView(this).apply { setOnClickListener { talk() } }
        root.addView(orb, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1.1f))

        status = TextView(this).apply {
            setTextColor(Color.WHITE); textSize = 22f; gravity = Gravity.CENTER; typeface = Typeface.DEFAULT_BOLD
        }
        root.addView(status)

        val texts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(12), 0, dp(12)) }
        transcript = TextView(this).apply { setTextColor(Color.rgb(143, 161, 174)); textSize = 15f }
        reply = TextView(this).apply { setTextColor(Color.WHITE); textSize = 19f; setPadding(0, dp(8), 0, 0) }
        changes = TextView(this).apply { setTextColor(Color.rgb(44, 196, 230)); textSize = 14f; setPadding(0, dp(8), 0, 0) }
        message = TextView(this).apply { setTextColor(Color.rgb(255, 196, 61)); textSize = 14f; setPadding(0, dp(8), 0, 0) }
        listOf(transcript, reply, changes, message).forEach { texts.addView(it) }
        root.addView(ScrollView(this).apply { addView(texts) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 0.9f))

        val bottom = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val lp = LinearLayout.LayoutParams(0, dp(56), 1f).apply { setMargins(dp(4), 0, dp(4), 0) }
        bottom.addView(bigButton("Terminer la session") { JarvisService.send(this, JarvisService.ACTION_END_SESSION) }, lp)
        startStop = bigButton("Arrêter Jarvis") {
            if (JarvisBus.state.phase == Phase.OFF) ensurePermissionsThenStart()
            else JarvisService.send(this, JarvisService.ACTION_STOP)
        }
        bottom.addView(startStop, LinearLayout.LayoutParams(0, dp(56), 1f).apply { setMargins(dp(4), 0, dp(4), 0) })
        root.addView(bottom)
        return root
    }

    private fun talk() {
        if (!config.isConfigured) {
            startActivity(Intent(this, SettingsActivity::class.java)); return
        }
        if (JarvisBus.state.phase == Phase.OFF) {
            ensurePermissionsThenStart()
            orb.postDelayed({ JarvisService.send(this, JarvisService.ACTION_TALK) }, 600)
        } else {
            JarvisService.send(this, JarvisService.ACTION_TALK)
        }
    }

    private fun openProjects() {
        if (config.serverUrl.isEmpty()) return
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(config.serverUrl + "/")))
    }

    private fun smallButton(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setTextColor(Color.rgb(155, 234, 251))
        background = null
        setOnClickListener { onClick() }
    }

    private fun bigButton(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        textSize = 16f
        setTextColor(Color.WHITE)
        background = GradientDrawable().apply { cornerRadius = dp(14).toFloat(); setColor(Color.rgb(25, 40, 52)) }
        setOnClickListener { onClick() }
    }
}
