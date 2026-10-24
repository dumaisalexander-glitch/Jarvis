package com.loryzon.jarvis

import android.content.Context

/** Réglages de l'app, gardés sur le téléphone. */
class Config(context: Context) {
    private val prefs = context.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString("serverUrl", "") ?: ""
        set(v) = prefs.edit().putString("serverUrl", v.trim().trimEnd('/')).apply()

    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(v) = prefs.edit().putString("token", v.trim()).apply()

    /** Écoute « Jarvis » en continu. */
    var wakeWord: Boolean
        get() = prefs.getBoolean("wakeWord", true)
        set(v) = prefs.edit().putBoolean("wakeWord", v).apply()

    /** Sensibilité du mot d'éveil (score minimum, 0.1 à 0.9). Plus bas = réagit plus facilement. */
    var threshold: Float
        get() = prefs.getFloat("threshold", 0.85f)
        set(v) = prefs.edit().putFloat("threshold", v.coerceIn(0.1f, 0.95f)).apply()

    /** Après la réponse, Jarvis réécoute tout de suite (conversation sans redire « Jarvis »). */
    var conversation: Boolean
        get() = prefs.getBoolean("conversation", true)
        set(v) = prefs.edit().putBoolean("conversation", v).apply()

    /** Minutes sans parler avant d'envoyer le résumé dans Teams. */
    var sessionTimeoutMin: Int
        get() = prefs.getInt("sessionTimeoutMin", 5)
        set(v) = prefs.edit().putInt("sessionTimeoutMin", v.coerceIn(1, 120)).apply()

    val isConfigured: Boolean get() = serverUrl.startsWith("https://") && token.isNotEmpty()
}
