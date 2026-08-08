package com.wanxiangupdater

import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader

/**
 * Root 权限工具：检测 su 可用性并以 root 身份执行 shell 命令。
 *
 * 用法示例：
 *   RootShell.isAvailable()          // 设备是否有可用 root
 *   RootShell.exec("id")             // 执行命令并返回 (exitCode, 合并输出)
 *   RootShell.mkdirs("/data/foo/bar")
 *   RootShell.copyFile(src, dest)    // 用 root 权限复制文件
 */
object RootShell {

    /** 常见 su 路径，按优先级尝试。 */
    private val SU_PATHS = listOf(
        "/system/xbin/su",
        "/system/bin/su",
        "/sbin/su",
        "/system/sd/xbin/su",
        "/vendor/bin/su"
    )

    /** su 命令的候选调用方式：路径在环境中时直接用 "su"，否则逐个试已知路径。 */
    private val SU_COMMANDS: List<List<String>> by lazy {
        val candidates = mutableListOf<List<String>>()
        // 优先信任 PATH 中的 su（Magisk 通常在此）
        candidates.add(listOf("su", "-c"))
        SU_PATHS.forEach { candidates.add(listOf(it, "-c")) }
        candidates
    }

    private var cachedSuAvailable: Boolean? = null

    /**
     * 设备是否有可用的 root 权限。
     * 结果会被缓存；需要重新检测时可传 forceRefresh=true。
     */
    fun isAvailable(forceRefresh: Boolean = false): Boolean {
        if (cachedSuAvailable != null && !forceRefresh) return cachedSuAvailable!!

        val result = runCatching {
            val (code, output) = exec("id")
            code == 0 && (output.contains("uid=0") || output.contains("uid=0("))
        }.getOrDefault(false)

        cachedSuAvailable = result
        return result
    }

    /**
     * 以 root 身份执行一条命令。
     * @return Pair(exitCode, stdout+stderr 合并输出)
     */
    fun exec(command: String): Pair<Int, String> {
        var lastError: Exception? = null

        for (suCmd in SU_COMMANDS) {
            try {
                val processBuilder = ProcessBuilder(suCmd + command)
                processBuilder.redirectErrorStream(true)
                val process = processBuilder.start()

                val output = StringBuilder()
                BufferedReader(InputStreamReader(process.inputStream)).use { reader ->
                    val buffer = CharArray(4096)
                    while (true) {
                        val count = reader.read(buffer)
                        if (count < 0) break
                        output.append(buffer, 0, count)
                    }
                }

                val exitCode = process.waitFor()
                val text = output.toString()
                // Magisk su 成功执行会回显一条 "uid=0(root) ..." 之类，无需过滤
                return exitCode to text.trim()
            } catch (error: Exception) {
                lastError = error
            }
        }

        throw (lastError ?: IllegalStateException("无可用 su 命令"))
    }

    /** 执行命令，命令字符串会经过 shell 转义，防止注入。 */
    private fun shellQuote(value: String): String = "'" + value.replace("'", "'\\''") + "'"

    /** 以 root 创建目录（含父目录）。成功返回 true。 */
    fun mkdirs(path: String): Boolean {
        val (code, _) = exec("mkdir -p ${shellQuote(path)}")
        return code == 0
    }

    /** 以 root 删除文件或目录（递归）。 */
    fun delete(path: String): Boolean {
        val (code, _) = exec("rm -rf ${shellQuote(path)}")
        return code == 0
    }

    /** 目标路径是否存在（root 视角）。 */
    fun exists(path: String): Boolean {
        val (code, _) = exec("test -e ${shellQuote(path)}")
        return code == 0
    }

    /** 目标路径是否为目录（root 视角）。 */
    fun isDirectory(path: String): Boolean {
        val (code, _) = exec("test -d ${shellQuote(path)}")
        return code == 0
    }

    /**
     * 用 root 权限复制单个文件。
     * 源文件必须在 root 可读的位置（app 私有目录 root 也能读）。
     * 目标目录需已存在（可先调用 mkdirs）。
     */
    fun copyFile(src: File, dest: File): Boolean {
        val (code, _) = exec("cat ${shellQuote(src.absolutePath)} > ${shellQuote(dest.absolutePath)}")
        if (code != 0) return false
        // root 视角校验大小一致（app 视角可能 stat 不到系统目录，dest.length() 恒为 0）
        val (_, sizeOut) = exec("wc -c < ${shellQuote(dest.absolutePath)} 2>/dev/null")
        val destSize = sizeOut.trim().toLongOrNull() ?: -1L
        return destSize == src.length()
    }

    /** 用 root 权限移动文件（原子替换常用）。 */
    fun move(srcPath: String, destPath: String): Boolean {
        val (code, _) = exec("mv -f ${shellQuote(srcPath)} ${shellQuote(destPath)}")
        return code == 0
    }

    /** root 视角读取文件大小（字节）。失败返回 -1。 */
    fun fileSize(path: String): Long {
        val (code, out) = exec("wc -c < ${shellQuote(path)} 2>/dev/null")
        if (code != 0) return -1L
        return out.trim().toLongOrNull() ?: -1L
    }

    /**
     * 用 root 权限将目录递归复制到目标路径。
     * 目标目录会被清空后重建（等价于 copyNormal 的语义）。
     * @return 错误信息列表（空 = 全部成功）
     */
    fun copyDirectory(src: File, dest: File, debug: (String) -> Unit = {}): List<String> {
        val errors = mutableListOf<String>()
        val srcRoot = src.absolutePath

        val files = src.walkTopDown().toList()
        for (file in files) {
            if (file.absolutePath == srcRoot) continue
            val relPath = file.relativeTo(src).path
            val targetFile = File(dest, relPath)

            if (file.isDirectory) {
                if (!mkdirs(targetFile.absolutePath)) {
                    errors.add("创建目录失败: $relPath")
                }
            } else {
                val parent = targetFile.parentFile
                if (parent == null || !mkdirs(parent.absolutePath)) {
                    errors.add("创建父目录失败: $relPath")
                    continue
                }
                if (!copyFile(file, targetFile)) {
                    errors.add("复制文件失败: $relPath")
                }
            }
        }
        return errors
    }
}
