package com.shomer.client.monitor

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import javax.inject.Inject
import javax.inject.Singleton

/**
 * In-memory, device-side log of recent monitor events and their upload status, so
 * the child-mode "Monitor Activity" screen can show what was captured and whether it
 * reached the server.
 *
 * This is a transparency / debugging surface (the consent flow already discloses that
 * messages are monitored). It holds only the most recent [MAX_ENTRIES] entries and is
 * cleared on process death — the durable record lives server-side, not here.
 */
@Singleton
class MonitorActivityLog @Inject constructor() {

    enum class Status { PENDING, SENT, FAILED }

    data class Entry(
        val clientMsgId: String,
        val text: String,
        val direction: String,
        val capturedAtMs: Long,
        val status: Status,
    )

    private val _entries = MutableStateFlow<List<Entry>>(emptyList())
    val entries: StateFlow<List<Entry>> = _entries

    /** Record a freshly buffered event (newest first), as PENDING. */
    fun recordCaptured(clientMsgId: String, text: String, direction: String, capturedAtMs: Long) {
        val entry = Entry(clientMsgId, text, direction, capturedAtMs, Status.PENDING)
        _entries.update { (listOf(entry) + it).take(MAX_ENTRIES) }
    }

    /** Mark the given client_msg_ids as successfully uploaded to the server. */
    fun markSent(ids: Collection<String>) = setStatus(ids, Status.SENT)

    /** Mark the given client_msg_ids as failed (auth error / permanent failure). */
    fun markFailed(ids: Collection<String>) = setStatus(ids, Status.FAILED)

    private fun setStatus(ids: Collection<String>, status: Status) {
        if (ids.isEmpty()) return
        val idSet = ids.toHashSet()
        _entries.update { list ->
            list.map { if (it.clientMsgId in idSet) it.copy(status = status) else it }
        }
    }

    companion object {
        private const val MAX_ENTRIES = 100
    }
}
