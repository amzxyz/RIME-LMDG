package com.wanxiangupdater

import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentLinkedQueue

const val WANXIANG_DEBUG_TAG = "WanxiangUpdater"
const val DOWNLOAD_SOURCE_CNB = "CNB"
const val DOWNLOAD_SOURCE_GITHUB = "GitHub"

class TaskState(
    val title: String,
    val url: String,
    val githubProbeUrl: String? = null,
    val kind: String = "package",
    val schemeType: String = "base",
    val auxScheme: String = "zrm"
) {
    var installName by mutableStateOf<String?>(null)
    var progress by mutableStateOf(0f)
    var status by mutableStateOf("等待中...")
    var isFinished by mutableStateOf(false)
    var isError by mutableStateOf(false)

    private val debugQueue = ConcurrentLinkedQueue<String>()
    var debugText by mutableStateOf("")
    var showDebug by mutableStateOf(false)

    fun appendDebug(message: String, error: Throwable? = null) {
        val time = SimpleDateFormat("HH:mm:ss.SSS", Locale.getDefault()).format(Date())
        debugQueue.add("[$time] $message")

        if (error == null) {
            Log.d(WANXIANG_DEBUG_TAG, "$title | $message")
        } else {
            Log.e(WANXIANG_DEBUG_TAG, "$title | $message", error)
        }
    }

    fun debugSnapshot(): String = debugQueue.joinToString("\n")
}
