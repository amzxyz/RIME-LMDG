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
import java.util.Locale

private const val EXTRA_DICT_RAW_BASE =
    "https://raw.githubusercontent.com/amzxyz/rime-wanxiang-data/wanxiang/dicts"

/**
 * 受控附加词库目录。这里维护不带后缀的仓库文件名；界面只展示这些条目，
 * 下载时统一补全为 .dict.yaml。
 */
data class ExtraDictCatalogEntry(
    val id: String,
    val description: String
)

val EXTRA_DICT_CATALOG: List<ExtraDictCatalogEntry> = listOf(
    ExtraDictCatalogEntry("shici", "诗词大全"),
    ExtraDictCatalogEntry("wuzhong", "动植物名称"),
    ExtraDictCatalogEntry("huaxue", "化学词库"),
    ExtraDictCatalogEntry("yaopin", "药品词库"),
    ExtraDictCatalogEntry("yixue", "医学词库"),
    ExtraDictCatalogEntry("fangyan", "国内方言词库")
)

private val EXTRA_DICT_IDS = EXTRA_DICT_CATALOG.map { it.id }.toSet()

fun loadSelectedExtraDictIds(raw: String?): Set<String> {
    return (raw ?: "")
        .split(Regex("[,，;；\\n]+"))
        .map { it.trim().substringBeforeLast(".dict.yaml", it, ignoreCase = true) }
        .filter { it in EXTRA_DICT_IDS }
        .toSet()
}

fun extraDictFileNames(selectedIds: Collection<String>): List<String> =
    EXTRA_DICT_CATALOG.filter { it.id in selectedIds }.map { "${it.id}.dict.yaml" }

fun normalizeExtraDictNames(text: String): List<String> = text.split(Regex("[,，;；\\n]+"))
    .map { it.trim() }
    .filter { it.isNotBlank() && "/" !in it && "\\\\" !in it }
    .map {
        when {
            it.endsWith(".dict.yaml", true) -> it
            it.endsWith(".yaml", true) -> it.dropLast(5) + ".dict.yaml"
            else -> "$it.dict.yaml"
        }
    }
    .distinctBy { it.lowercase(Locale.ROOT) }

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
