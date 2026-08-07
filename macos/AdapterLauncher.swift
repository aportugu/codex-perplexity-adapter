import AppKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var keyField: NSSecureTextField!
    private var startButton: NSButton!
    private var stopButton: NSButton!
    private var statusLabel: NSTextField!
    private var serverProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildWindow()
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopServer()
    }

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 300),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Codex–Perplexity Adapter"
        window.isReleasedWhenClosed = false

        let content = NSView()
        content.translatesAutoresizingMaskIntoConstraints = false
        window.contentView = content

        let title = NSTextField(labelWithString: "Codex–Perplexity Adapter")
        title.font = .systemFont(ofSize: 24, weight: .semibold)

        let description = NSTextField(wrappingLabelWithString:
            "Runs a private local Responses API at 127.0.0.1:4000 for Codex and Positron. Your Perplexity key stays in this process and is never saved."
        )
        description.textColor = .secondaryLabelColor

        let keyLabel = NSTextField(labelWithString: "Perplexity API key")
        keyLabel.font = .systemFont(ofSize: 13, weight: .medium)

        keyField = NSSecureTextField()
        keyField.placeholderString = "pplx-…"
        keyField.target = self
        keyField.action = #selector(startClicked)

        startButton = NSButton(title: "Start Adapter", target: self, action: #selector(startClicked))
        startButton.bezelStyle = .rounded
        startButton.keyEquivalent = "\r"

        stopButton = NSButton(title: "Stop", target: self, action: #selector(stopClicked))
        stopButton.bezelStyle = .rounded
        stopButton.isEnabled = false

        statusLabel = NSTextField(labelWithString: "● Stopped")
        statusLabel.textColor = .secondaryLabelColor

        let buttonRow = NSStackView(views: [startButton, stopButton, statusLabel])
        buttonRow.orientation = .horizontal
        buttonRow.spacing = 10
        buttonRow.alignment = .centerY

        let stack = NSStackView(views: [title, description, keyLabel, keyField, buttonRow])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(stack)

        keyField.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        description.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 28),
        ])
    }

    @objc private func startClicked() {
        guard serverProcess == nil else { return }
        let apiKey = keyField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !apiKey.isEmpty else {
            showAlert("Enter your Perplexity API key before starting the adapter.")
            return
        }
        guard let executable = Bundle.main.url(forResource: "adapter-server", withExtension: nil) else {
            showAlert("The bundled adapter server is missing. Reinstall the application.")
            return
        }

        let process = Process()
        process.executableURL = executable
        process.arguments = ["--host", "127.0.0.1", "--port", "4000", "--log-level", "info"]
        var environment = ProcessInfo.processInfo.environment
        environment["PERPLEXITY_API_KEY"] = apiKey
        process.environment = environment

        let logDirectory = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs", isDirectory: true)
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        let logURL = logDirectory.appendingPathComponent("Codex Perplexity Adapter.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let logHandle = try? FileHandle(forWritingTo: logURL) {
            try? logHandle.seekToEnd()
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self, self.serverProcess === finished else { return }
                self.serverProcess = nil
                self.setRunning(false)
                if finished.terminationStatus != 0 {
                    self.statusLabel.stringValue = "● Could not start — port 4000 may be in use"
                    self.statusLabel.textColor = .systemRed
                }
            }
        }

        do {
            try process.run()
            serverProcess = process
            keyField.stringValue = ""
            setRunning(true)
            verifyHealth()
        } catch {
            showAlert("The adapter could not start: \(error.localizedDescription)")
        }
    }

    @objc private func stopClicked() {
        stopServer()
        setRunning(false)
    }

    private func stopServer() {
        if let process = serverProcess, process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
        serverProcess = nil
    }

    private func setRunning(_ running: Bool) {
        startButton.isEnabled = !running
        stopButton.isEnabled = running
        keyField.isEnabled = !running
        statusLabel.stringValue = running ? "● Starting…" : "● Stopped"
        statusLabel.textColor = running ? .systemOrange : .secondaryLabelColor
    }

    private func verifyHealth(attempt: Int = 0) {
        guard serverProcess?.isRunning == true else { return }
        let request = URLRequest(url: URL(string: "http://127.0.0.1:4000/health")!, timeoutInterval: 1)
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self, self.serverProcess?.isRunning == true else { return }
                if let http = response as? HTTPURLResponse, http.statusCode == 200, data != nil {
                    self.statusLabel.stringValue = "● Running at 127.0.0.1:4000"
                    self.statusLabel.textColor = .systemGreen
                } else if attempt < 12 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        self.verifyHealth(attempt: attempt + 1)
                    }
                } else {
                    self.statusLabel.stringValue = "● Server did not become ready"
                    self.statusLabel.textColor = .systemRed
                }
            }
        }.resume()
    }

    private func showAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Codex–Perplexity Adapter"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }
}

@main
struct AdapterLauncher {
    static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.run()
    }
}
