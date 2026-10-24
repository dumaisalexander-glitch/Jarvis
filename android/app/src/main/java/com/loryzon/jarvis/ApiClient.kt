package com.loryzon.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Parle au serveur Jarvis (Vercel). */
class ApiClient(private val config: Config) {

    data class Reply(
        val transcription: String,
        val reponse: String,
        val changements: List<String>,
        val finSession: Boolean,
    )

    fun converse(pcm: ShortArray, length: Int, sessionId: String): Reply {
        val body = wav(pcm, length)
        val json = post("/api/converse", body, "audio/wav", sessionId)
        val list = json.optJSONArray("changements") ?: JSONArray()
        return Reply(
            transcription = json.optString("transcription"),
            reponse = json.optString("reponse", "Désolé, je n'ai pas de réponse."),
            changements = List(list.length()) { list.getString(it) },
            finSession = json.optBoolean("finSession", false),
        )
    }

    fun endSession(sessionId: String): String {
        val payload = JSONObject().put("session", sessionId).toString().toByteArray()
        val json = post("/api/session-end", payload, "application/json", sessionId)
        val teams = json.optJSONObject("teams")
        return if (teams?.optBoolean("envoye") == true) "Résumé envoyé dans Teams." else
            "Résumé enregistré" + (teams?.optString("raison")?.let { " ($it)" } ?: "") + "."
    }

    fun health(): String {
        val conn = open("/api/health", "GET", null, "")
        return read(conn).toString()
    }

    private fun post(path: String, body: ByteArray, type: String, sessionId: String): JSONObject {
        val conn = open(path, "POST", type, sessionId)
        conn.doOutput = true
        conn.setFixedLengthStreamingMode(body.size)
        conn.outputStream.use { it.write(body) }
        return read(conn)
    }

    private fun open(path: String, method: String, type: String?, sessionId: String): HttpURLConnection {
        val conn = URL(config.serverUrl + path).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 15_000
        conn.readTimeout = 70_000
        conn.setRequestProperty("Authorization", "Bearer ${config.token}")
        conn.setRequestProperty("X-Device", "android")
        if (sessionId.isNotEmpty()) conn.setRequestProperty("X-Session", sessionId)
        if (type != null) conn.setRequestProperty("Content-Type", type)
        return conn
    }

    private fun read(conn: HttpURLConnection): JSONObject {
        try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            val json = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
            if (code == 401) throw IllegalStateException("Mot de passe Jarvis refusé par le serveur.")
            if (code !in 200..299) {
                throw IllegalStateException(json.optString("erreur").ifEmpty { "Erreur du serveur ($code)" })
            }
            return json
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        /** Emballe l'audio 16 kHz mono 16 bits dans un fichier WAV. */
        fun wav(pcm: ShortArray, length: Int, sampleRate: Int = 16000): ByteArray {
            val dataBytes = length * 2
            val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
                put("RIFF".toByteArray()); putInt(36 + dataBytes); put("WAVE".toByteArray())
                put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1)
                putInt(sampleRate); putInt(sampleRate * 2); putShort(2); putShort(16)
                put("data".toByteArray()); putInt(dataBytes)
            }
            val data = ByteBuffer.allocate(dataBytes).order(ByteOrder.LITTLE_ENDIAN)
            for (i in 0 until length) data.putShort(pcm[i])
            return ByteArrayOutputStream(44 + dataBytes).apply {
                write(header.array()); write(data.array())
            }.toByteArray()
        }
    }
}
