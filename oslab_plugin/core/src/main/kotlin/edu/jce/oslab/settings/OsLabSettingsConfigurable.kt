package edu.jce.oslab.settings

import com.intellij.openapi.options.Configurable
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.FormBuilder
import javax.swing.JComponent
import javax.swing.JPanel

/** Settings → Tools → OS Lab. */
class OsLabSettingsConfigurable : Configurable {

    private val backendUrlField = JBTextField()
    private val devCodeField = JBTextField()
    private var panel: JPanel? = null

    override fun getDisplayName(): String = "OS Lab"

    override fun createComponent(): JComponent {
        val built = FormBuilder.createFormBuilder()
            .addLabeledComponent(JBLabel("Backend URL:"), backendUrlField, 1, false)
            .addComponentToRightColumn(
                JBLabel("The FastAPI backend. Defaults to the class tunnel; use http://127.0.0.1:8000 when running it locally."),
            )
            .addLabeledComponent(JBLabel("Dev auto-login code:"), devCodeField, 1, false)
            .addComponentToRightColumn(
                JBLabel("Optional. If set, the OS Lab tool window logs in automatically. Leave blank in class."),
            )
            .addComponentFillVertically(JPanel(), 0)
            .panel
        panel = built
        return built
    }

    override fun isModified(): Boolean {
        val s = OsLabSettings.instance
        return backendUrlField.text.trim().trimEnd('/') != s.backendUrl ||
            devCodeField.text.trim() != s.devLoginCode
    }

    override fun apply() {
        val s = OsLabSettings.instance
        s.backendUrl = backendUrlField.text
        s.devLoginCode = devCodeField.text
    }

    override fun reset() {
        val s = OsLabSettings.instance
        backendUrlField.text = s.backendUrl
        devCodeField.text = s.devLoginCode
    }

    override fun disposeUIResources() {
        panel = null
    }
}
