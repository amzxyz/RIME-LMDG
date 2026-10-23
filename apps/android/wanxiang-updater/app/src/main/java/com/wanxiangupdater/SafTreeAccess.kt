package com.wanxiangupdater

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.documentfile.provider.DocumentFile
import java.util.UUID

/** 每一个 SAF Tree URI 对应独立的系统授权；SharedPreferences 中保存 URI 并不代表权限仍有效。 */
data class SafTreeHealth(val ok: Boolean, val message: String) {
    companion object {
        val OK = SafTreeHealth(true, "已持久授权，读写探测成功")
    }
}

object SafTreeAccess {
    private const val BOTH = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION

    /** 返回系统选择器的 Intent，旧位置只用于定位，不能绕过用户点击“使用此文件夹”。 */
    fun pickerIntent(previousUri: String? = null): Intent =
        Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(BOTH or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            if (android.os.Build.VERSION.SDK_INT >= 26 && previousUri?.startsWith("content://") == true) {
                putExtra(DocumentsContract.EXTRA_INITIAL_URI, Uri.parse(previousUri))
            }
        }

    /** 只在系统选择器返回明确的读写标志后保存；失败时上层不能持久化此路径。 */
    fun persistPickedTree(context: Context, resultData: Intent): Uri {
        val treeUri = resultData.data ?: throw IllegalArgumentException("未返回任何目录")
        if (treeUri.scheme != "content" || !DocumentsContract.isTreeUri(treeUri)) {
            throw SecurityException("选择结果不是 SAF 目录授权")
        }
        val granted = resultData.flags and BOTH
        if (granted != BOTH) throw SecurityException("系统未同时授予读取与写入权限，请选择可写目录")
        context.contentResolver.takePersistableUriPermission(treeUri, granted)
        val saved = context.contentResolver.persistedUriPermissions.any {
            it.uri == treeUri && it.isReadPermission && it.isWritePermission
        }
        if (!saved) throw SecurityException("无法持久保存读写授权，请重新选择目录")
        return treeUri
    }

    /** 启动/回前台：先检查真实持久化授权，再检查 Provider 是否仍存在并可写。 */
    fun check(context: Context, uriString: String): SafTreeHealth {
        val uri = runCatching { Uri.parse(uriString) }.getOrNull()
            ?: return SafTreeHealth(false, "记录的目录地址无效")
        if (uri.scheme != "content" || !DocumentsContract.isTreeUri(uri)) {
            return SafTreeHealth(false, "不是合法 SAF 目录 URI")
        }
        val permission = try {
            context.contentResolver.persistedUriPermissions.firstOrNull { it.uri == uri }
        } catch (e: Exception) {
            return SafTreeHealth(false, "查询系统授权失败：${e.message ?: e.javaClass.simpleName}")
        }
        if (permission == null) return SafTreeHealth(false, "系统已没有此目录的持久授权（升级、清除数据或重新安装后可能发生）")
        if (!permission.isReadPermission || !permission.isWritePermission) {
            return SafTreeHealth(false, "只保留了部分授权，缺少读取或写入权限")
        }
        val root = try {
            DocumentFile.fromTreeUri(context, uri)
                ?: return SafTreeHealth(false, "无法解析目录（文件提供者可能不可用）")
        } catch (e: Exception) {
            return SafTreeHealth(false, "目录提供者不可用：${e.message ?: e.javaClass.simpleName}")
        }
        try {
            if (!root.exists() || !root.isDirectory) return SafTreeHealth(false, "目录已移动、删除或不再可访问")
            if (!root.canRead()) return SafTreeHealth(false, "该目录无法读取，请重新授权")
        } catch (e: Exception) {
            return SafTreeHealth(false, "无法读取目录元数据：${e.message ?: e.javaClass.simpleName}")
        }
        val probeError = probeWrite(context, uri)
        return if (probeError == null) SafTreeHealth.OK else SafTreeHealth(false, probeError)
    }

    /** 写入实际的临时小文件并删除，测试与部署一致的 create/openOutputStream/delete 能力。
     * 不改动用户文件；失败时尽可能清除探测文件。必须在 IO 线程调用。 */
    fun probeWrite(context: Context, treeUri: Uri): String? {
        val root = try { DocumentFile.fromTreeUri(context, treeUri) }
        catch (e: Exception) { return "无法打开 SAF 目录：${e.message ?: e.javaClass.simpleName}" }
            ?: return "无法解析 SAF 目录"
        try {
            if (!root.exists() || !root.isDirectory) return "SAF 目录不存在或不可访问"
        } catch (e: Exception) { return "无法检查 SAF 目录：${e.message ?: e.javaClass.simpleName}" }
        val name = "wanxiang_write_probe_${UUID.randomUUID()}.tmp"
        val created = try { root.createFile("application/octet-stream", name) }
        catch (e: Exception) { return "SAF 创建文件失败：${e.message ?: e.javaClass.simpleName}" }
            ?: return "SAF 拒绝创建文件（可能是只读目录）"
        var error: String? = null
        try {
            val stream = context.contentResolver.openOutputStream(created.uri, "w")
                ?: throw java.io.IOException("文件提供者未提供写入流")
            stream.use {
                it.write(byteArrayOf(0x57, 0x58))
                it.flush()
            }
        } catch (e: Exception) {
            error = "SAF 写入失败：${e.message ?: e.javaClass.simpleName}"
        } finally {
            val deleted = try { created.delete() } catch (_: Exception) { false }
            if (!deleted) {
                error = listOfNotNull(error, "SAF 探测文件无法删除（请检查目录写入权限）").joinToString("；")
            }
        }
        return error
    }
}
