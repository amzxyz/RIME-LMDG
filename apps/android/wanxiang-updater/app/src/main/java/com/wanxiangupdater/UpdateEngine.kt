package com.wanxiangupdater

import android.content.Context
import android.net.Uri
import android.os.Environment
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong
import java.util.zip.ZipFile
import java.util.zip.ZipInputStream

fun executeTasks(
    urls: List<String>,
    scope: kotlinx.coroutines.CoroutineScope,
    setDownloading: (Boolean) -> Unit,
    setTasks: (List<TaskState>) -> Unit,
    targetPaths: List<String>,
    context: Context,
    rules: List<String>,
    githubProbeUrls: Map<String, String> = emptyMap(),
    extraDictNames: List<String> = emptyList(),
    schemeType: String = "base",
    auxScheme: String = "zrm"
) {
    scope.launch {
        setDownloading(true)
        val packageTasks = urls.map { url ->
            val fileName = url.substringBefore("?").substringAfterLast("/")
            val title = when {
                fileName.contains("dicts", true) -> "词库包"
                fileName.contains("gram", true) -> "模型"
                else -> "方案"
            }
            TaskState("$title ($fileName)", url, githubProbeUrls[url])
        }
        val extraTasks = extraDictNames.map { fileName ->
            val url = extraDictRawUrl(fileName)
            TaskState("附加词库 ($fileName)", url, kind = "extra", schemeType = schemeType, auxScheme = auxScheme)
        }
        val activeTasks = packageTasks + extraTasks

        setTasks(activeTasks)
        for (task in activeTasks) {
            downloadAndDeployTask(
                task = task,
                targetPaths = targetPaths,
                context = context,
                rules = rules
            )
            if (task.isError) break
        }
        setDownloading(false)
    }
}

fun isUsableZip(file: File): Boolean {
    return try {
        ZipFile(file).use { zip -> zip.entries().hasMoreElements() }
    } catch (_: Exception) {
        false
    }
}

fun looksLikeErrorPayload(file: File): Boolean {
    return try {
        val prefix = file.inputStream().buffered().use { input ->
            val buffer = ByteArray(512)
            val count = input.read(buffer)
            if (count <= 0) "" else String(buffer, 0, count, Charsets.UTF_8)
        }.trimStart().lowercase()

        prefix.startsWith("<!doctype html") ||
            prefix.startsWith("<html") ||
            prefix.startsWith("{\"message\"") ||
            prefix.startsWith("{\"error\"") ||
            prefix.startsWith("access denied") ||
            prefix.startsWith("bad gateway")
    } catch (_: Exception) {
        false
    }
}

fun sanitizedFileName(url: String): String {
    val raw = url.substringBefore("?").substringAfterLast("/").ifBlank { "download.bin" }
    return raw.replace(Regex("""[\\/:*?"<>|]"""), "_")
}

fun formatDownloadSpeed(bytesPerSecond: Long): String {
    return if (bytesPerSecond >= 1024L * 1024L) {
        String.format("%.1fMB/s", bytesPerSecond / 1024.0 / 1024.0)
    } else {
        "${bytesPerSecond / 1024L}KB/s"
    }
}

suspend fun downloadAndDeployTask(
    task: TaskState,
    targetPaths: List<String>,
    context: Context,
    rules: List<String>
) {
    withContext(Dispatchers.IO) {
        val stagingDir = File(context.cacheDir, "wanxiang_staging/${UUID.randomUUID()}")
        val tmpFile = File(stagingDir, "${sanitizedFileName(task.url)}.tmp")
        var success = false
        var lastErrorMsg = ""
        var downloadedFrom = ""

        task.appendDebug("任务开始")
        task.appendDebug("源地址：${task.url}")
        task.appendDebug("目标路径：${targetPaths.joinToString { deployPathDisplayName(it) }}")
        task.appendDebug("缓存目录：${stagingDir.absolutePath}")
        task.appendDebug("下载前执行轻量目标探测")
        publishTaskDebug(task)

        var usableTargetPaths = emptyList<String>()

        try {
            val usableTargets = mutableListOf<String>()
            val skippedTargets = mutableListOf<String>()

            targetPaths
                .map { it.trim() }
                .filter { it.isNotBlank() }
                .distinct()
                .forEach { path ->
                    val pathName = deployPathDisplayName(path)

                    if (path == "DEFAULT") {
                        if (canWriteDefaultRime()) {
                            usableTargets.add(path)
                            task.appendDebug("目标可用：$pathName（所有文件访问权限已授予）")
                        } else {
                            skippedTargets.add("$pathName：缺少所有文件访问权限")
                            task.appendDebug("跳过目标：$pathName（缺少所有文件访问权限）")
                        }
                        return@forEach
                    }

                    if (isRootTarget(path)) {
                        if (RootShell.isAvailable()) {
                            usableTargets.add(path)
                            task.appendDebug("目标可用：$pathName（root 权限已就绪）")
                        } else {
                            skippedTargets.add("$pathName：设备无 root 权限")
                            task.appendDebug("跳过目标：$pathName（设备无 root 权限）")
                        }
                        return@forEach
                    }

                    val uri = runCatching { Uri.parse(path) }.getOrNull()
                    if (uri == null) {
                        skippedTargets.add("$pathName：SAF地址无效")
                        task.appendDebug("跳过目标：$pathName（SAF地址无效）")
                        return@forEach
                    }

                    val probeError = probeSafTreeWriteAccess(context, uri)
                    if (probeError == null) {
                        usableTargets.add(path)
                        task.appendDebug("目标可用：$pathName（SAF小文件探测通过）")
                    } else {
                        skippedTargets.add("$pathName：$probeError")
                        task.appendDebug("跳过目标：$pathName（$probeError）")
                    }
                }

            usableTargetPaths = usableTargets

            if (skippedTargets.isNotEmpty()) {
                task.appendDebug("本次跳过目标：${skippedTargets.joinToString()}")
            }
            publishTaskDebug(task)

            if (usableTargetPaths.isEmpty()) {
                withContext(Dispatchers.Main) {
                    task.isError = true
                    task.progress = 0f
                    task.status = "❌ 没有可写目标"
                }
                return@withContext
            }

            if (!stagingDir.mkdirs() && !stagingDir.isDirectory) {
                throw Exception("无法创建临时目录")
            }

            withContext(Dispatchers.Main) {
                task.isFinished = false
                task.isError = false
                task.progress = 0f
                task.status = "准备中..."
            }

            val isLocalFile = task.url.startsWith("/") ||
                task.url.startsWith("file://") ||
                task.url.startsWith("content://")

            if (isLocalFile) {
                try {
                    withContext(Dispatchers.Main) {
                        task.status = "读取本地文件..."
                        task.progress = -1f
                    }

                    val uri = if (task.url.startsWith("/")) Uri.fromFile(File(task.url)) else Uri.parse(task.url)
                    context.contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(tmpFile).buffered().use { output -> input.copyTo(output) }
                    } ?: throw Exception("找不到文件或无权限读取该本地路径")

                    if (!tmpFile.exists() || tmpFile.length() == 0L) throw Exception("本地文件为空")
                    task.appendDebug("本地文件读取完成：${tmpFile.length()} 字节")
                    success = true
                    downloadedFrom = "本地文件"

                    withContext(Dispatchers.Main) {
                        task.progress = 1f
                        task.status = "本地读取完成"
                    }
                } catch (error: Exception) {
                    lastErrorMsg = error.message ?: "本地文件读取异常"
                    task.appendDebug("本地文件读取失败：${error.javaClass.simpleName}: $lastErrorMsg", error)
                    publishTaskDebug(task)
                }
            } else {
                // CNB 模式下先向对应 GitHub Release 发一次 4 字节 GET。
                // 该操作完全静默，失败不会记录、不会重试、不会影响 CNB 下载。
                task.githubProbeUrl?.let { silentGithubShortDownloadRequest(it) }

                val expectedZip = task.url.substringBefore("?").endsWith(".zip", true)
                val sourceName = when {
                    task.url.contains("cnb.cool", true) -> "CNB"
                    task.url.contains("github.com", true) -> "GitHub"
                    else -> runCatching { URL(task.url).host }.getOrDefault("直链")
                }

                // 恢复旧版下载过程：手动追踪重定向 -> HEAD 取长度 -> 三线程分段；
                // 无法获得长度时自动改用单线程。最多重试 3 次，不再经过任何代理。
                for (attempt in 1..3) {
                    var finalUrlStr = task.url
                    try {
                        tmpFile.delete()
                        withContext(Dispatchers.Main) {
                            task.progress = 0f
                            task.status = if (attempt > 1) {
                                "$sourceName 重试中($attempt/3)"
                            } else {
                                "连接 $sourceName..."
                            }
                        }
                        task.appendDebug("开始下载：$sourceName，第 $attempt 次，url=${task.url}")

                        var redirectCount = 0
                        while (redirectCount < 5) {
                            var redirectConn: HttpURLConnection? = null
                            try {
                                val redirectUrl = URL(finalUrlStr)
                                redirectConn = redirectUrl.openConnection() as HttpURLConnection
                                redirectConn.instanceFollowRedirects = false
                                redirectConn.requestMethod = "HEAD"
                                redirectConn.connectTimeout = 10000
                                redirectConn.readTimeout = 10000
                                redirectConn.setRequestProperty(
                                    "User-Agent",
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                )

                                val code = redirectConn.responseCode
                                task.appendDebug("重定向探测：code=$code，url=$finalUrlStr")
                                if (code in listOf(301, 302, 303, 307, 308)) {
                                    val location = redirectConn.getHeaderField("Location")
                                    if (!location.isNullOrBlank()) {
                                        finalUrlStr = if (location.startsWith("http")) {
                                            location
                                        } else {
                                            URL(redirectUrl, location).toString()
                                        }
                                        redirectCount++
                                        continue
                                    }
                                }
                                break
                            } finally {
                                redirectConn?.disconnect()
                            }
                        }

                        val finalUrl = URL(finalUrlStr)
                        var totalSize = 0L
                        var rangeSupported = false
                        var sizeConn: HttpURLConnection? = null

                        try {
                            sizeConn = finalUrl.openConnection() as HttpURLConnection
                            sizeConn.requestMethod = "HEAD"
                            sizeConn.connectTimeout = 10000
                            sizeConn.readTimeout = 10000
                            sizeConn.setRequestProperty(
                                "User-Agent",
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            )
                            sizeConn.setRequestProperty("Accept-Encoding", "identity")

                            val code = sizeConn.responseCode
                            if (code == 200 || code == 206) {
                                totalSize = sizeConn.getHeaderFieldLong("Content-Length", -1L).coerceAtLeast(0L)
                                rangeSupported = sizeConn.getHeaderField("Accept-Ranges")
                                    ?.contains("bytes", true) == true
                            }
                            task.appendDebug(
                                "文件信息：code=$code，size=$totalSize，acceptRanges=$rangeSupported，final=$finalUrlStr"
                            )
                        } finally {
                            sizeConn?.disconnect()
                        }

                        if (totalSize > 0L && rangeSupported) {
                            val threadCount = 3
                            val chunkSize = totalSize / threadCount
                            val downloadedLen = AtomicLong(0L)
                            val lastUpdateTime = AtomicLong(System.currentTimeMillis())
                            val partFiles = (0 until threadCount).map { index ->
                                File(stagingDir, "${tmpFile.name}.part$index")
                            }

                            try {
                                coroutineScope {
                                    (0 until threadCount).map { index ->
                                        async(Dispatchers.IO) {
                                            val start = index * chunkSize
                                            val end = if (index == threadCount - 1) {
                                                totalSize - 1
                                            } else {
                                                start + chunkSize - 1
                                            }

                                            var partConn: HttpURLConnection? = null
                                            try {
                                                partConn = URL(finalUrlStr).openConnection() as HttpURLConnection
                                                partConn.connectTimeout = 10000
                                                partConn.readTimeout = 15000
                                                partConn.setRequestProperty(
                                                    "User-Agent",
                                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                                )
                                                partConn.setRequestProperty("Range", "bytes=$start-$end")
                                                partConn.setRequestProperty("Accept-Encoding", "identity")

                                                val responseCode = partConn.responseCode
                                                if (responseCode != 206) {
                                                    throw Exception("服务器未接受分段请求：HTTP $responseCode")
                                                }

                                                val partFile = partFiles[index]
                                                partConn.inputStream.buffered().use { input ->
                                                    FileOutputStream(partFile).buffered().use { output ->
                                                        val data = ByteArray(64 * 1024)
                                                        while (true) {
                                                            val count = input.read(data)
                                                            if (count < 0) break
                                                            output.write(data, 0, count)

                                                            val currentDownloaded = downloadedLen.addAndGet(count.toLong())
                                                            val currentTime = System.currentTimeMillis()
                                                            val previous = lastUpdateTime.get()
                                                            if (currentTime - previous > 150L &&
                                                                lastUpdateTime.compareAndSet(previous, currentTime)
                                                            ) {
                                                                val speedText = formatDownloadSpeed(
                                                                    currentDownloaded * 1000L /
                                                                        (currentTime - previous + 1L).coerceAtLeast(1L)
                                                                )
                                                                withContext(Dispatchers.Main) {
                                                                    task.progress = (currentDownloaded.toDouble() / totalSize.toDouble())
                                                                        .toFloat()
                                                                        .coerceIn(0f, 1f)
                                                                    task.status = "$sourceName ${String.format("%.1f", currentDownloaded / 1024.0 / 1024.0)}MB / " +
                                                                        "${String.format("%.1f", totalSize / 1024.0 / 1024.0)}MB · 多线程"
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            } finally {
                                                partConn?.disconnect()
                                            }
                                        }
                                    }.awaitAll()
                                }

                                val expectedPartSizes = (0 until threadCount).map { index ->
                                    val start = index * chunkSize
                                    val end = if (index == threadCount - 1) totalSize - 1 else start + chunkSize - 1
                                    end - start + 1
                                }
                                partFiles.forEachIndexed { index, partFile ->
                                    if (!partFile.exists() || partFile.length() != expectedPartSizes[index]) {
                                        throw Exception(
                                            "分段文件不完整：part$index ${partFile.length()}/${expectedPartSizes[index]}"
                                        )
                                    }
                                }

                                withContext(Dispatchers.Main) { task.status = "文件拼装中..." }
                                FileOutputStream(tmpFile).buffered().use { output ->
                                    partFiles.forEach { partFile ->
                                        partFile.inputStream().buffered().use { input -> input.copyTo(output) }
                                    }
                                }
                            } finally {
                                partFiles.forEach { it.delete() }
                            }
                        } else {
                            var conn: HttpURLConnection? = null
                            try {
                                conn = URL(finalUrlStr).openConnection() as HttpURLConnection
                                conn.instanceFollowRedirects = true
                                conn.connectTimeout = 10000
                                conn.readTimeout = 60000
                                conn.setRequestProperty(
                                    "User-Agent",
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                )
                                conn.setRequestProperty("Accept-Encoding", "identity")

                                val responseCode = conn.responseCode
                                if (responseCode !in 200..299) throw Exception("HTTP $responseCode")
                                val fallbackSize = conn.getHeaderFieldLong("Content-Length", -1L)
                                withContext(Dispatchers.Main) {
                                    task.progress = if (fallbackSize > 0L) 0f else -1f
                                }

                                var downloaded = 0L
                                val transferStartedAt = System.currentTimeMillis()
                                var lastUiUpdate = 0L
                                conn.inputStream.buffered().use { input ->
                                    FileOutputStream(tmpFile).buffered().use { output ->
                                        val data = ByteArray(128 * 1024)
                                        while (true) {
                                            val count = input.read(data)
                                            if (count < 0) break
                                            output.write(data, 0, count)
                                            downloaded += count

                                            val now = System.currentTimeMillis()
                                            if (now - lastUiUpdate >= 150L) {
                                                lastUiUpdate = now
                                                val elapsed = (now - transferStartedAt).coerceAtLeast(1L)
                                                val speed = formatDownloadSpeed(downloaded * 1000L / elapsed)
                                                withContext(Dispatchers.Main) {
                                                    if (fallbackSize > 0L) {
                                                        task.progress = (downloaded.toDouble() / fallbackSize.toDouble())
                                                            .toFloat()
                                                            .coerceIn(0f, 1f)
                                                        task.status = "$sourceName ${String.format("%.1f", downloaded / 1024.0 / 1024.0)}MB / " +
                                                            "${String.format("%.1f", fallbackSize / 1024.0 / 1024.0)}MB · $speed"
                                                    } else {
                                                        task.progress = -1f
                                                        task.status = "$sourceName ${String.format("%.1f", downloaded / 1024.0 / 1024.0)}MB · $speed"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                if (fallbackSize > 0L && tmpFile.length() != fallbackSize) {
                                    throw Exception("文件不完整：${tmpFile.length()}/$fallbackSize")
                                }
                            } finally {
                                conn?.disconnect()
                            }
                        }

                        if (!tmpFile.exists() || tmpFile.length() == 0L) throw Exception("下载文件为空")
                        if (looksLikeErrorPayload(tmpFile)) {
                            throw Exception("服务器返回了错误内容（${tmpFile.length()}B）")
                        }
                        if (expectedZip && !isUsableZip(tmpFile)) {
                            throw Exception("返回内容不是有效ZIP（${tmpFile.length()}B）")
                        }

                        success = true
                        downloadedFrom = sourceName
                        task.appendDebug("下载校验通过：来源=$sourceName，大小=${tmpFile.length()} 字节")
                        publishTaskDebug(task)

                        withContext(Dispatchers.Main) {
                            task.progress = 1f
                            task.status = "下载完成（$sourceName）"
                        }
                        break
                    } catch (error: Exception) {
                        lastErrorMsg = "$sourceName: ${error.message ?: "网络异常"}"
                        task.appendDebug(
                            "下载失败：$lastErrorMsg (${error.javaClass.simpleName})",
                            error
                        )
                        tmpFile.delete()

                        withContext(Dispatchers.Main) {
                            task.progress = 0f
                            task.status = "⚠️ $lastErrorMsg"
                        }
                        if (attempt < 3) delay(1000)
                    }
                }
            }

            if (!success) {
                task.appendDebug("下载失败：$lastErrorMsg")
                publishTaskDebug(task)
                withContext(Dispatchers.Main) {
                    task.isError = true
                    task.progress = 0f
                    task.status = "❌ 获取文件失败：$lastErrorMsg"
                }
                return@withContext
            }

            if (task.kind == "extra") {
                withContext(Dispatchers.Main) {
                    task.status = when (task.schemeType) {
                        "pro", "pure" -> "刷新辅助码中..."
                        "lite" -> "去除声调中..."
                        else -> "整理词库中..."
                    }
                }
                processExtraDictFile(context, tmpFile, task, targetPaths)
                task.appendDebug("附加词库处理完成：输出=${task.installName ?: sanitizedFileName(task.url)}")
                publishTaskDebug(task)
            }

            withContext(Dispatchers.Main) {
                task.status = if (isUsableZip(tmpFile)) "解压中..." else "部署中..."
                task.progress = -1f
            }

            val extractDir = File(stagingDir, "extracted")
            if (!extractDir.mkdirs() && !extractDir.isDirectory) throw Exception("无法创建解压目录")

            val isZipArchive = isUsableZip(tmpFile)
            task.appendDebug(
                "文件识别：name=${sanitizedFileName(task.url)}, size=${tmpFile.length()}, isZip=$isZipArchive"
            )

            if (isZipArchive) {
                val canonicalRoot = extractDir.canonicalFile
                ZipInputStream(tmpFile.inputStream().buffered()).use { zis ->
                    var entry = zis.nextEntry
                    while (entry != null) {
                        val outputFile = File(canonicalRoot, entry.name).canonicalFile
                        val insideRoot = outputFile.path == canonicalRoot.path ||
                            outputFile.path.startsWith(canonicalRoot.path + File.separator)
                        if (!insideRoot) throw Exception("压缩包包含危险路径：${entry.name}")

                        if (entry.isDirectory) {
                            if (!outputFile.mkdirs() && !outputFile.isDirectory) {
                                throw Exception("无法创建目录：${entry.name}")
                            }
                        } else {
                            outputFile.parentFile?.let { parent ->
                                if (!parent.mkdirs() && !parent.isDirectory) {
                                    throw Exception("无法创建目录：${parent.name}")
                                }
                            }
                            FileOutputStream(outputFile).buffered().use { output -> zis.copyTo(output) }
                        }
                        zis.closeEntry()
                        entry = zis.nextEntry
                    }
                }
            } else {
                val stagedFile = File(extractDir, task.installName ?: sanitizedFileName(task.url))
                if (stagedFile.exists() && !stagedFile.delete()) {
                    throw Exception("无法清理缓存中的旧临时文件：${stagedFile.name}")
                }

                if (!tmpFile.renameTo(stagedFile)) {
                    tmpFile.inputStream().buffered().use { input ->
                        FileOutputStream(stagedFile, false).buffered().use { output -> input.copyTo(output) }
                    }
                    if (!tmpFile.delete()) tmpFile.deleteOnExit()
                }
            }

            var realSrcDir = extractDir
            val subFiles = extractDir.listFiles()
            if (subFiles != null && subFiles.size == 1 && subFiles[0].isDirectory) {
                realSrcDir = subFiles[0]
            }

            task.appendDebug(
                "暂存完成：realSrc=${realSrcDir.absolutePath}，顶层=" +
                    realSrcDir.listFiles().orEmpty().take(20).joinToString {
                        "${it.name}${if (it.isDirectory) "/" else "(${it.length()}B)"}"
                    }
            )
            publishTaskDebug(task)

            val excludeRegexList = rules.mapNotNull {
                try {
                    Regex(it)
                } catch (_: Exception) {
                    null
                }
            }
            val isDict = task.url.contains("dicts", true)

            var successCount = 0
            val errorList = mutableListOf<String>()
            val orderedTargetPaths = usableTargetPaths.sortedBy { if (it == "DEFAULT") 1 else 0 }

            task.appendDebug("实际部署顺序：${orderedTargetPaths.joinToString { deployPathDisplayName(it) }}")
            publishTaskDebug(task)

            val fileDebug: (String) -> Unit = { message -> task.appendDebug(message) }

            for ((index, pathStr) in orderedTargetPaths.withIndex()) {
                val pathName = deployPathDisplayName(pathStr)

                try {
                    task.appendDebug("开始目标：$pathName，raw=$pathStr")
                    if (index > 0) delay(300)

                    withContext(Dispatchers.Main) {
                        task.status = "部署 $pathName ${index + 1}/${orderedTargetPaths.size}（$downloadedFrom）..."
                    }

                    if (pathStr == "DEFAULT") {
                        if (!canWriteDefaultRime()) throw Exception("缺少所有文件访问权限，已跳过")

                        val root = File(Environment.getExternalStorageDirectory(), "rime")
                        val target = if (isDict) File(root, "dicts") else root
                        task.appendDebug(
                            "普通目录：root=${root.absolutePath}, target=${target.absolutePath}, " +
                                "exists=${target.exists()}, canWrite=${target.canWrite()}"
                        )
                        copyNormal(realSrcDir, target, excludeRegexList, debug = fileDebug)
                    } else if (isRootTarget(pathStr)) {
                        if (!RootShell.isAvailable()) throw Exception("设备无 root 权限，已跳过")

                        val targetRoot = File(rootTargetPath(pathStr))
                        val target = if (isDict) File(targetRoot, "dicts") else targetRoot
                        task.appendDebug(
                            "Root目录：target=${target.absolutePath}, " +
                                "exists=${RootShell.exists(target.absolutePath)}"
                        )
                        copyRoot(realSrcDir, target, excludeRegexList, debug = fileDebug)
                    } else {
                        val targetUri = Uri.parse(pathStr)
                        val rootDoc = DocumentFile.fromTreeUri(context, targetUri)
                            ?: throw Exception("无法解析SAF授权目录")

                        var targetDoc = rootDoc
                        if (isDict) {
                            targetDoc = rootDoc.findFile("dicts")
                                ?: rootDoc.createDirectory("dicts")
                                ?: rootDoc.findFile("dicts")
                                ?: throw Exception("SAF底层拒绝创建dicts目录")
                        }

                        task.appendDebug(
                            "SAF目录：name=${targetDoc.name}, uri=${targetDoc.uri}, " +
                                "exists=${targetDoc.exists()}, canWrite=${targetDoc.canWrite()}"
                        )
                        copySaf(context, realSrcDir, targetDoc, excludeRegexList, debug = fileDebug)
                    }

                    successCount++
                    task.appendDebug("目标成功：$pathName")
                    publishTaskDebug(task)
                } catch (error: Exception) {
                    val detail = "$pathName(${error.javaClass.simpleName}: ${error.message ?: "无错误信息"})"
                    errorList.add(detail)
                    task.appendDebug("目标失败：$detail", error)
                    publishTaskDebug(task)
                }
            }

            task.appendDebug(
                "部署汇总：success=$successCount/${orderedTargetPaths.size}, errors=${errorList.joinToString()}"
            )
            publishTaskDebug(task)

            withContext(Dispatchers.Main) {
                val successText = if (isZipArchive) "解压并部署完成" else "文件部署完成"
                when {
                    successCount == orderedTargetPaths.size && orderedTargetPaths.isNotEmpty() -> {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "✅ $successText（$downloadedFrom）"
                    }
                    successCount > 0 -> {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "⚠️ 部分完成 [失败: ${errorList.joinToString()}]"
                    }
                    else -> {
                        task.isError = true
                        task.progress = 0f
                        task.status = "❌ 全部部署失败 [${errorList.joinToString()}]"
                    }
                }
            }
        } catch (error: Exception) {
            task.appendDebug(
                "任务级异常：${error.javaClass.name}: ${error.message ?: "无错误信息"}",
                error
            )
            publishTaskDebug(task)
            withContext(Dispatchers.Main) {
                task.isError = true
                task.progress = 0f
                task.status = "❌ 文件处理失败：${error.message ?: error.javaClass.simpleName}"
            }
        } finally {
            val deleted = stagingDir.deleteRecursively()
            task.appendDebug("清理缓存：$deleted，path=${stagingDir.absolutePath}")
            publishTaskDebug(task)
        }
    }
}
