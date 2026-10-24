package edu.jce.vericlass.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

/**
 * Persisted, application-level plugin settings. Only the connection details
 * live here — what the *client does* (chat vs. ide) is owned by the backend's
 * STUDENT_CLIENT_MODE and fetched at runtime, so there is no mode toggle here.
 */
@State(name = "VeriClassSettings", storages = [Storage("vericlass.xml")])
class VeriClassSettings : PersistentStateComponent<VeriClassSettings.State> {

    data class State(
        // Defaults to the always-on tunnel so a fresh install on a student's
        // machine reaches the teacher's backend without any setup. Keep this in
        // sync with deploy/tunnel.conf (NGROK_DOMAIN). Teachers running the
        // backend locally can point this at http://127.0.0.1:8000 in Settings.
        var backendUrl: String = "https://upgrade-nape-smasher.ngrok-free.dev",
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
        val instance: VeriClassSettings
            get() = ApplicationManager.getApplication().getService(VeriClassSettings::class.java)
    }
}
