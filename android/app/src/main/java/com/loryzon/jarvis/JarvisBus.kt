package com.loryzon.jarvis

import android.os.Handler
import android.os.Looper

/** Ce que le service fait en ce moment, partagé avec l'écran. */
enum class Phase(val label: String) {
    OFF("Arrêté"),
    IDLE("Dis « Jarvis » ou touche le bouton"),
    IDLE_NO_WAKE("Touche le bouton pour parler"),
    LISTENING("Je t'écoute…"),
    THINKING("Je réfléchis…"),
    SPEAKING("Je réponds…"),
}

object JarvisBus {
    data class Snapshot(
        val phase: Phase = Phase.OFF,
        val transcript: String = "",
        val reply: String = "",
        val changes: List<String> = emptyList(),
        val message: String = "",
        val level: Float = 0f,
    )

    private val main = Handler(Looper.getMainLooper())
    private val listeners = mutableSetOf<(Snapshot) -> Unit>()

    @Volatile var state = Snapshot()
        private set

    fun update(transform: (Snapshot) -> Snapshot) {
        synchronized(this) { state = transform(state) }
        val s = state
        main.post { listeners.toList().forEach { it(s) } }
    }

    fun listen(l: (Snapshot) -> Unit) { listeners += l; l(state) }
    fun unlisten(l: (Snapshot) -> Unit) { listeners -= l }
}
