package edu.jce.oslab.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

/**
 * Persisted, application-level plugin settings. Only the connection details
 * live here — what the *client does* (chat vs. ide) is owned by the backend's
 * STUDENT_CLIENT_MODE and fetched at runtime, so there is no mode toggle here.
 */
@State(name = "OsLabSettings", storages = [Storage("oslab.xml")])
class OsLabSettings : PersistentStateComponent<OsLabSettings.State> {

    data class State(
        var backendUrl: String = "http://127.0.0.1:8000",
        /** Dev convenience: if set, the tool window auto-logs in with this code. */
        var devLoginCode: String = "",
    )

    private var state = State()

    override fun getState(): State = state

    override fun loadState(s: State) {
        state = s
    }

    var backendUrl: String
        get() = state.backendUrl.trim().trimEnd('/')
        set(value) {
            state.backendUrl = value.trim()
        }

    var devLoginCode: String
        get() = state.devLoginCode.trim()
        set(value) {
            state.devLoginCode = value.trim()
        }

    companion object {
        val instance: OsLabSettings
            get() = ApplicationManager.getApplication().getService(OsLabSettings::class.java)
    }
}
