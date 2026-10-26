package com.movix.tv.player

import android.net.Uri
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.TransferListener

/**
 * Envoie chaque requête vers [okHttp] ou [primary] selon son hôte.
 *
 * Fsvid/Vidzy exigent l'Accept-Encoding exact de Chrome (« gzip, deflate,
 * br, zstd ») : Cronet le réécrit en « gzip, deflate, br » (relevé le
 * 2026-10-26) et reçoit leur faux master. Leurs requêtes passent donc par
 * OkHttp, le reste garde Cronet.
 */
class HostRoutingDataSource(
    private val primary: DataSource,
    private val okHttp: DataSource,
    private val useOkHttp: (Uri) -> Boolean,
) : DataSource {
    private var current: DataSource? = null

    override fun addTransferListener(transferListener: TransferListener) {
        primary.addTransferListener(transferListener)
        okHttp.addTransferListener(transferListener)
    }

    override fun open(dataSpec: DataSpec): Long {
        val source = if (useOkHttp(dataSpec.uri)) okHttp else primary
        current = source
        return source.open(dataSpec)
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
        checkNotNull(current) { "read() avant open()" }.read(buffer, offset, length)

    override fun getUri(): Uri? = current?.uri

    override fun getResponseHeaders(): Map<String, List<String>> = current?.responseHeaders ?: emptyMap()

    override fun close() {
        try {
            current?.close()
        } finally {
            current = null
        }
    }

    class Factory(
        private val primary: DataSource.Factory,
        private val okHttp: DataSource.Factory,
        private val useOkHttp: (Uri) -> Boolean,
    ) : DataSource.Factory {
        override fun createDataSource(): DataSource =
            HostRoutingDataSource(primary.createDataSource(), okHttp.createDataSource(), useOkHttp)
    }

    companion object {
        /** Hôtes dont le CDN exige l'Accept-Encoding exact de Chrome. */
        fun needsExactChromeEncoding(uri: Uri): Boolean {
            val host = uri.host?.lowercase()?.trimEnd('.') ?: return false
            return listOf("fsvid.lol", "vidzy.cc", "vidzy.org").any { host == it || host.endsWith(".$it") }
        }
    }
}
