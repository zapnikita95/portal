package org.portal.portal_downloads

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileInputStream

class PortalAndroidDownloadsPlugin : FlutterPlugin, MethodChannel.MethodCallHandler {
    private lateinit var channel: MethodChannel
    private lateinit var context: Context

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        channel = MethodChannel(binding.binaryMessenger, "org.portal.portal/downloads")
        channel.setMethodCallHandler(this)
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "saveToDownloadsPortal" -> {
                val path = call.argument<String>("path")
                val displayName = call.argument<String>("displayName") ?: "file"
                if (path == null) {
                    result.success(mapOf("ok" to false, "error" to "no_path"))
                    return
                }
                try {
                    val ok = saveToDownloadsPortal(context, path, displayName)
                    result.success(mapOf("ok" to ok))
                } catch (e: Exception) {
                    result.success(
                        mapOf("ok" to false, "error" to (e.message ?: "exception")),
                    )
                }
            }
            else -> result.notImplemented()
        }
    }
}

private fun guessMime(name: String): String {
    val lower = name.lowercase()
    return when {
        lower.endsWith(".png") -> "image/png"
        lower.endsWith(".jpg") || lower.endsWith(".jpeg") -> "image/jpeg"
        lower.endsWith(".gif") -> "image/gif"
        lower.endsWith(".webp") -> "image/webp"
        lower.endsWith(".pdf") -> "application/pdf"
        lower.endsWith(".txt") -> "text/plain"
        lower.endsWith(".zip") -> "application/zip"
        else -> "application/octet-stream"
    }
}

/**
 * Копия в **Download/Portal** (видно в системном приложении «Загрузки»).
 * API 29+: MediaStore. Ниже — прямой путь в public Download.
 */
fun saveToDownloadsPortal(context: Context, sourcePath: String, displayName: String): Boolean {
    val src = File(sourcePath)
    if (!src.isFile || !src.canRead()) return false
    val len = src.length()
    if (len <= 0L) return false

    val resolver = context.contentResolver
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, guessMime(displayName))
            put(
                MediaStore.MediaColumns.RELATIVE_PATH,
                Environment.DIRECTORY_DOWNLOADS + "/Portal",
            )
        }
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val uri = resolver.insert(collection, values) ?: return false
        resolver.openOutputStream(uri)?.use { out ->
            FileInputStream(src).use { input -> input.copyTo(out) }
        } ?: return false
        return true
    }

    val dir = File(
        Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
        "Portal",
    )
    if (!dir.exists() && !dir.mkdirs()) return false
    val dest = File(dir, displayName)
    if (dest.exists()) dest.delete()
    src.copyTo(dest, overwrite = true)
    return dest.isFile && dest.length() == len
}
