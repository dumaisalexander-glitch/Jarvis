package com.loryzon.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View
import kotlin.math.min
import kotlin.math.sin

/** Le gros bouton rond de Jarvis. Sa couleur et son mouvement montrent ce qu'il fait. */
class OrbView(context: Context) : View(context) {
    var phase: Phase = Phase.OFF
        set(v) { field = v; invalidate() }
    var level: Float = 0f
    private var shown = 0f
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val start = System.nanoTime()

    init {
        isClickable = true
        isFocusable = true
        contentDescription = "Parler à Jarvis"
    }

    private fun color(): Int = when (phase) {
        Phase.LISTENING -> Color.rgb(255, 82, 82)
        Phase.THINKING -> Color.rgb(255, 196, 61)
        Phase.SPEAKING -> Color.rgb(44, 196, 230)
        Phase.OFF -> Color.rgb(70, 80, 90)
        else -> Color.rgb(30, 140, 170)
    }

    override fun onDraw(canvas: Canvas) {
        val t = (System.nanoTime() - start) / 1e9f
        val cx = width / 2f
        val cy = height / 2f
        val r = min(width, height) * 0.36f
        shown += (level - shown) * 0.3f
        val pulse = when (phase) {
            Phase.LISTENING -> 0.06f + shown * 0.25f
            Phase.THINKING -> 0.04f * sin(t * 6f)
            Phase.SPEAKING -> 0.05f * sin(t * 9f)
            Phase.IDLE, Phase.IDLE_NO_WAKE -> 0.02f * sin(t * 1.5f)
            Phase.OFF -> 0f
        }
        val c = color()
        // halo
        paint.shader = RadialGradient(cx, cy, r * 1.6f, intArrayOf(withAlpha(c, 110), withAlpha(c, 0)), null, Shader.TileMode.CLAMP)
        canvas.drawCircle(cx, cy, r * (1.45f + pulse), paint)
        // anneau
        paint.shader = null
        paint.color = c
        canvas.drawCircle(cx, cy, r * (1f + pulse), paint)
        paint.color = Color.rgb(11, 18, 24)
        canvas.drawCircle(cx, cy, r * 0.72f, paint)
        // cœur
        paint.shader = RadialGradient(cx, cy, r * 0.45f, intArrayOf(Color.WHITE, c), null, Shader.TileMode.CLAMP)
        canvas.drawCircle(cx, cy, r * (0.38f + pulse * 0.8f), paint)
        paint.shader = null
        if (phase != Phase.OFF) postInvalidateOnAnimation()
    }

    private fun withAlpha(c: Int, a: Int) = Color.argb(a, Color.red(c), Color.green(c), Color.blue(c))
}
