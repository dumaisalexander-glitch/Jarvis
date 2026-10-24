package com.loryzon.jarvis

import android.app.Activity
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Switch
import android.widget.TextView
import java.util.concurrent.Executors

class SettingsActivity : Activity() {

    private lateinit var config: Config

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        config = Config(this)
        setContentView(buildUi())
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun buildUi(): View {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(20))
            setBackgroundColor(Color.rgb(11, 18, 24))
        }
        fun label(t: String, size: Float = 15f, color: Int = Color.rgb(143, 161, 174)) =
            TextView(this).apply { text = t; textSize = size; setTextColor(color); setPadding(0, dp(14), 0, dp(4)) }
        fun field(value: String, hint: String, password: Boolean = false) = EditText(this).apply {
            setText(value); this.hint = hint
            setTextColor(Color.WHITE); setHintTextColor(Color.rgb(80, 95, 105))
            inputType = if (password) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            isSingleLine = true
        }

        col.addView(label("Réglages de Jarvis", 22f, Color.WHITE))

        col.addView(label("Adresse du serveur Jarvis (Vercel)"))
        val url = field(config.serverUrl, "https://mon-jarvis.vercel.app")
        col.addView(url)

        col.addView(label("Mot de passe Jarvis (JARVIS_TOKEN)"))
        val token = field(config.token, "le même que sur Vercel", password = true)
        col.addView(token)

        val wake = Switch(this).apply {
            text = "Écouter « Jarvis » en continu"; setTextColor(Color.WHITE); textSize = 16f
            isChecked = config.wakeWord; setPadding(0, dp(18), 0, 0)
        }
        col.addView(wake)

        val sensLabel = label("")
        col.addView(sensLabel)
        val sens = SeekBar(this).apply { max = 85 }
        // barre : 0 = peu sensible (seuil 0,95) ... 85 = très sensible (seuil 0,1)
        sens.progress = ((0.95f - config.threshold) * 100).toInt().coerceIn(0, 85)
        fun updateSens() {
            sensLabel.text = "Sensibilité du mot d'éveil : seuil %.2f (plus bas = réagit plus facilement)".format(0.95f - sens.progress / 100f)
        }
        updateSens()
        sens.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, fromUser: Boolean) = updateSens()
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })
        col.addView(sens)

        val convo = Switch(this).apply {
            text = "Mode conversation (Jarvis réécoute après avoir répondu)"; setTextColor(Color.WHITE); textSize = 16f
            isChecked = config.conversation; setPadding(0, dp(18), 0, 0)
        }
        col.addView(convo)

        col.addView(label("Minutes de silence avant d'envoyer le résumé dans Teams"))
        val timeout = field(config.sessionTimeoutMin.toString(), "5").apply { inputType = InputType.TYPE_CLASS_NUMBER }
        col.addView(timeout)

        val result = label("")
        fun save() {
            config.serverUrl = url.text.toString()
            config.token = token.text.toString()
            config.wakeWord = wake.isChecked
            config.threshold = 0.95f - sens.progress / 100f
            config.conversation = convo.isChecked
            config.sessionTimeoutMin = timeout.text.toString().toIntOrNull() ?: 5
        }

        col.addView(button("Tester la connexion") {
            save()
            result.text = "Test en cours…"
            Executors.newSingleThreadExecutor().execute {
                val msg = try {
                    val h = org.json.JSONObject(ApiClient(config).health())
                    val manque = listOf("whisper" to "clé Whisper", "claude" to "clé Claude", "base_de_donnees" to "base de données", "teams" to "Teams")
                        .filter { !h.optBoolean(it.first) }.map { it.second }
                    if (manque.isEmpty()) "✔ Tout est prêt (modèle ${h.optString("modele")})."
                    else "Connecté, mais il manque sur Vercel : ${manque.joinToString(", ")}."
                } catch (e: Exception) {
                    "✘ ${e.message ?: "Connexion impossible"}"
                }
                runOnUiThread { result.text = msg }
            }
        })
        col.addView(result)

        col.addView(button("Enregistrer") {
            save()
            if (JarvisBus.state.phase != Phase.OFF) JarvisService.send(this, JarvisService.ACTION_RELOAD)
            finish()
        })

        return ScrollView(this).apply { setBackgroundColor(Color.rgb(11, 18, 24)); addView(col) }
    }

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        textSize = 16f
        setTextColor(Color.WHITE)
        background = GradientDrawable().apply { cornerRadius = dp(14).toFloat(); setColor(Color.rgb(0, 134, 168)) }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(52)).apply { topMargin = dp(18) }
        setOnClickListener { onClick() }
    }
}
