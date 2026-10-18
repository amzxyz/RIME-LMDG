package com.wanxiangupdater

import android.content.Context
import android.net.Uri
import android.os.Environment
import androidx.documentfile.provider.DocumentFile
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONArray

private const val EXTRA_DICT_RAW_BASE =
    "https://raw.githubusercontent.com/amzxyz/rime-wanxiang-data/wanxiang/dicts"
private const val EXTRA_DICT_CATALOG_URL =
    "https://raw.githubusercontent.com/amzxyz/rime-wanxiang-data/wanxiang/extra-dicts.json"
private const val EXTRA_DICT_CATALOG_CACHE = "extra-dicts.json"
private const val EXTRA_DICT_CATALOG_TEMP = "extra-dicts.json.tmp"

/**
 * 受控附加词库目录。这里维护不带后缀的仓库文件名；界面只展示这些条目，
 * 下载时统一补全为 .dict.yaml。
 */
data class ExtraDictCatalogEntry(
    val id: String,
    val name: String
)

private fun parseExtraDictCatalog(text: String): List<ExtraDictCatalogEntry> {
    val array = JSONArray(text)
    require(array.length() <= 200) { "附加词库目录过大" }
    val result = mutableListOf<ExtraDictCatalogEntry>()
    val seen = mutableSetOf<String>()
    for (index in 0 until array.length()) {
        val item = array.optJSONObject(index) ?: continue
        val id = item.optString("id").trim().lowercase()
        val name = item.optString("name").trim()
        if (!Regex("[a-z0-9][a-z0-9_-]{0,63}").matches(id)) continue
        if (name.isBlank() || name.length > 80 || !seen.add(id)) continue
        result += ExtraDictCatalogEntry(id, name)
    }
    require(result.isNotEmpty()) { "附加词库目录为空" }
    return result
}

fun readCachedExtraDictCatalog(context: Context): List<ExtraDictCatalogEntry> =
    runCatching {
        context.openFileInput(EXTRA_DICT_CATALOG_CACHE).bufferedReader(Charsets.UTF_8).use { reader ->
            parseExtraDictCatalog(reader.readText())
        }
    }.getOrDefault(emptyList())

suspend fun refreshExtraDictCatalog(context: Context): Result<List<ExtraDictCatalogEntry>> =
    withContext(Dispatchers.IO) {
        runCatching {
            val connection = (URL(EXTRA_DICT_CATALOG_URL).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 5000
                readTimeout = 15000
                useCaches = true
                setRequestProperty("Accept", "application/json")
                setRequestProperty("User-Agent", "Wanxiang-Updater")
            }
            try {
                check(connection.responseCode in 200..299) { "HTTP ${connection.responseCode}" }
                val bytes = connection.inputStream.use { it.readBytes() }
                check(bytes.size <= 256 * 1024) { "配置文件过大" }
                val catalog = parseExtraDictCatalog(bytes.toString(Charsets.UTF_8))
                val temp = File(context.filesDir, EXTRA_DICT_CATALOG_TEMP)
                temp.writeText(
                    JSONArray().apply {
                        catalog.forEach { entry ->
                            put(org.json.JSONObject().apply {
                                put("id", entry.id)
                                put("name", entry.name)
                            })
                        }
                    }.toString(),
                    Charsets.UTF_8
                )
                val target = File(context.filesDir, EXTRA_DICT_CATALOG_CACHE)
                if (!temp.renameTo(target)) {
                    temp.copyTo(target, overwrite = true)
                    temp.delete()
                }
                catalog
            } finally {
                connection.disconnect()
            }
        }
    }

fun extraDictFileNames(
    selectedIds: Collection<String>,
    catalog: Collection<ExtraDictCatalogEntry>
): List<String> = catalog.filter { it.id in selectedIds }.map { "${it.id}.dict.yaml" }

fun extraDictRawUrl(fileName: String): String =
    "$EXTRA_DICT_RAW_BASE/${java.net.URLEncoder.encode(fileName, "UTF-8").replace("+", "%20")}"

fun extraOutputName(fileName: String, suffix: String): String =
    if (suffix.isBlank()) fileName
    else if (fileName.endsWith(".dict.yaml", true))
        fileName.dropLast(".dict.yaml".length) + suffix + ".dict.yaml"
    else fileName + suffix + ".dict.yaml"

private object MobileToolsPythonBridge {
    private val lock = Any()

    private fun python(context: Context): Python {
        if (!Python.isStarted()) synchronized(lock) {
            if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        }
        return Python.getInstance()
    }

    fun process(context: Context, src: File, dst: File, scheme: String, auxText: String): String {
        return python(context).getModule("mobile_tools_bridge")
            .callAttr("process_extra_file", src.absolutePath, dst.absolutePath, scheme, auxText)
            .toString()
    }
}

private fun readAuxTextFromTargets(context: Context, targetPaths: List<String>): String {
    for (path in targetPaths) {
        val text = runCatching {
            when {
                path == "DEFAULT" -> File(Environment.getExternalStorageDirectory(), "rime/dicts/zi.pro.dict.yaml")
                    .takeIf { it.isFile }?.readText(Charsets.UTF_8)
                isRootTarget(path) -> File(rootTargetPath(path), "dicts/zi.pro.dict.yaml")
                    .takeIf { it.isFile }?.readText(Charsets.UTF_8)
                else -> {
                    val root = DocumentFile.fromTreeUri(context, Uri.parse(path))
                    val file = root?.findFile("dicts")?.findFile("zi.pro.dict.yaml")
                    file?.let { context.contentResolver.openInputStream(it.uri)?.bufferedReader(Charsets.UTF_8)?.use { r -> r.readText() } }
                }
            }
        }.getOrNull()
        if (!text.isNullOrBlank()) return text
    }
    return ""
}

/** Process to a separate file, then atomically replace the downloaded staging file. */
fun processExtraDictFile(context: Context, file: File, task: TaskState, targetPaths: List<String>) {
    val originalName = sanitizedFileName(task.url)
    val suffix = when (task.schemeType) {
        "pro" -> ".pro"
        "lite" -> ".lite"
        else -> ""
    }
    val outputName = extraOutputName(originalName, suffix)
    if (task.schemeType == "pure" || task.schemeType == "base") {
        task.installName = outputName
        return
    }
    val parent = file.parentFile ?: throw IllegalStateException("临时目录无效")
    val output = File(parent, "$outputName.processed")
    val auxText = if (task.schemeType == "pro") readAuxTextFromTargets(context, targetPaths) else ""
    if (task.schemeType == "pro" && auxText.isBlank()) {
        throw IllegalStateException("找不到 zi.pro.dict.yaml，无法刷新附加词库辅助码")
    }
    val result = MobileToolsPythonBridge.process(context, file, output, task.schemeType, auxText)
    if (!output.isFile() || output.length() == 0L) throw IllegalStateException("词库处理未生成输出")
    if (!file.delete() || !output.renameTo(file)) throw IllegalStateException("无法替换处理后的词库文件")
    task.installName = outputName
    task.appendDebug("Python 词库处理：$result")
}
