import Foundation
import AppKit
import PDFKit
import Security
import LocalAuthentication
import Darwin

// Passwords stay inside this process/Keychain. Never print OS error objects,
// password values, or extracted text to stdout/stderr.
enum Failure: Error { case message(String) }
let service = "com.moneylens.codex.pdf-password"

func keychainQuery(_ account: String) -> [String: Any] {
    [kSecClass as String: kSecClassGenericPassword,
     kSecAttrService as String: service, kSecAttrAccount as String: account]
}
func savedPassword(_ account: String, noPrompt: Bool = false) throws -> String? {
    var query = keychainQuery(account)
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    if noPrompt {
        let context = LAContext()
        context.interactionNotAllowed = true
        query[kSecUseAuthenticationContext as String] = context
    }
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = item as? Data,
          let password = String(data: data, encoding: .utf8) else {
        throw Failure.message("Keychain access failed (status \(status)). No plaintext fallback.")
    }
    return password
}
func savePassword(_ password: String, _ account: String) throws {
    let query = keychainQuery(account)
    let updates = [kSecValueData as String: Data(password.utf8)]
    var status = SecItemUpdate(query as CFDictionary, updates as CFDictionary)
    if status == errSecItemNotFound {
        var addition = query
        addition[kSecValueData as String] = Data(password.utf8)
        addition[kSecAttrLabel as String] = "MoneyLens statement PDF password"
        addition[kSecAttrSynchronizable as String] = false
        status = SecItemAdd(addition as CFDictionary, nil)
    }
    guard status == errSecSuccess else {
        throw Failure.message("Could not save password in Keychain (status \(status)).")
    }
}
func prompt(_ filename: String) throws -> String {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let alert = NSAlert()
    alert.messageText = "Unlock statement for MoneyLens"
    alert.informativeText = "File: \(filename)\nEnter the PDF password. After a successful unlock it will be saved in this Mac's Keychain for the selected card or document. It is not sent to chat."
    alert.addButton(withTitle: "Unlock and Save")
    alert.addButton(withTitle: "Cancel")
    let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 26))
    alert.accessoryView = field
    alert.window.initialFirstResponder = field
    app.activate(ignoringOtherApps: true)
    guard alert.runModal() == .alertFirstButtonReturn else {
        throw Failure.message("Cancelled. Statement was not extracted.")
    }
    return field.stringValue
}

func derivedPasswords() throws -> [String] {
    let raw = FileHandle.standardInput.readDataToEndOfFile()
    guard raw.count <= 16_384,
          let data = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
          let attributes = data["attributes"] as? [String: String],
          let recipes = data["recipes"] as? [String], !recipes.isEmpty, recipes.count <= 3 else {
        throw Failure.message("Expected a small stdin JSON object with known attributes and at most three document-supported recipes.")
    }
    let name = (attributes["full_name"] ?? "").filter { $0.isLetter }
    let prefix = String(name.prefix(4))
    let card = attributes["card_last4"] ?? ""
    var birthday = attributes["birth_ddmm"] ?? ""
    if birthday.isEmpty, let birth = attributes["birth_date"] {
        let parts = birth.split(separator: "-")
        if parts.count == 3 { birthday = String(parts[2]) + String(parts[1]) }
    }
    var result: [String] = []
    for recipe in recipes {
        var value: String?
        switch recipe {
        case "name4_upper_card_last4":
            if prefix.count == 4 && card.count == 4 && card.allSatisfy({ $0.isNumber }) { value = prefix.uppercased() + card }
        case "name4_lower_birth_ddmm":
            if prefix.count == 4 && birthday.count == 4 && birthday.allSatisfy({ $0.isNumber }) { value = prefix.lowercased() + birthday }
        case "name4_upper_birth_ddmm":
            if prefix.count == 4 && birthday.count == 4 && birthday.allSatisfy({ $0.isNumber }) { value = prefix.uppercased() + birthday }
        default:
            throw Failure.message("Unsupported recipe. Use the exact issuer instructions or the local masked password prompt.")
        }
        if let value = value, !result.contains(value) { result.append(value) }
    }
    return result
}

func run() throws {
    umask(0o077)
    let args = Array(CommandLine.arguments.dropFirst())
    if args == ["--help"] || args.isEmpty {
        print("pdf-extract --input PDF --output JSON --account OPAQUE-SCOPE [--previous-account OLD-SCOPE] [--probe] [--no-prompt] [--derive-from-stdin]\nMetadata only: --keychain-status --account OPAQUE-SCOPE\nSynthetic verification without Keychain: --input PDF --verify-derived-only (JSON on stdin)")
        return
    }
    var options: [String: String] = [:]
    var probe = false
    var noPrompt = false
    var keychainStatus = false
    var derive = false
    var verifyDerived = false
    var index = 0
    while index < args.count {
        if args[index] == "--probe" { probe = true; index += 1; continue }
        if args[index] == "--no-prompt" { noPrompt = true; index += 1; continue }
        if args[index] == "--keychain-status" { keychainStatus = true; index += 1; continue }
        if args[index] == "--derive-from-stdin" { derive = true; index += 1; continue }
        if args[index] == "--verify-derived-only" { derive = true; verifyDerived = true; index += 1; continue }
        guard ["--input", "--output", "--account", "--previous-account"].contains(args[index]),
              index + 1 < args.count, options[args[index]] == nil else {
            throw Failure.message("Invalid arguments; use --help.")
        }
        options[args[index]] = args[index + 1]
        index += 2
    }
    if keychainStatus {
        guard let scope = options["--account"], !scope.isEmpty else { throw Failure.message("--account is required.") }
        var query = keychainQuery(scope)
        query[kSecReturnAttributes as String] = true
        let context = LAContext()
        context.interactionNotAllowed = true
        query[kSecUseAuthenticationContext as String] = context
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecSuccess { print("{\"credential_present\":true}"); return }
        if status == errSecItemNotFound { print("{\"credential_present\":false}"); return }
        throw Failure.message("Keychain status unavailable without interaction (status \(status)).")
    }
    guard !noPrompt || options["--previous-account"] == nil else {
        throw Failure.message("Credential migration is available only during interactive setup.")
    }
    guard !noPrompt || !derive else { throw Failure.message("Derive and save passwords during setup; daily runs use saved credentials without prompts.") }
    guard let input = options["--input"] else { throw Failure.message("--input is required.") }
    let inputURL = URL(fileURLWithPath: input).standardizedFileURL
    let attrs = try FileManager.default.attributesOfItem(atPath: inputURL.path)
    guard let size = attrs[.size] as? NSNumber, size.intValue <= 20 * 1024 * 1024,
          let pdf = PDFDocument(url: inputURL) else {
        throw Failure.message("Unreadable PDF or input exceeds 20 MiB.")
    }
    if probe {
        print("{\"encrypted\":\(pdf.isEncrypted),\"locked\":\(pdf.isLocked),\"page_count\":\(pdf.pageCount)}")
        return  // Pure metadata: never reads Keychain or opens a password prompt.
    }
    var candidates = derive ? try derivedPasswords() : []
    if verifyDerived {
        guard pdf.isLocked else { throw Failure.message("Derivation verification needs a locked PDF.") }
        var attempts = 0
        for candidate in candidates {
            attempts += 1
            if pdf.unlock(withPassword: candidate) {
                print("{\"derived_unlock\":true,\"attempts\":\(attempts)}")
                return
            }
        }
        throw Failure.message("Known attributes did not unlock this PDF; missing or incorrect input needs clarification.")
    }
    guard let output = options["--output"], let scope = options["--account"], !scope.isEmpty else {
        throw Failure.message("--output and nonempty --account are required.")
    }
    let outputURL = URL(fileURLWithPath: output).standardizedFileURL
    guard outputURL.resolvingSymlinksInPath() != inputURL.resolvingSymlinksInPath(),
          !FileManager.default.fileExists(atPath: outputURL.path) else {
        throw Failure.message("Output must be a new file, separate from the PDF.")
    }
    if pdf.isLocked {
        var password = try savedPassword(scope, noPrompt: noPrompt)
        var copied = false
        if password == nil, let previous = options["--previous-account"] {
            password = try savedPassword(previous, noPrompt: noPrompt)
            copied = password != nil
        }
        var unlocked = false
        if let value = password { unlocked = pdf.unlock(withPassword: value) }
        if !unlocked {
            for candidate in candidates {
                if pdf.unlock(withPassword: candidate) {
                    password = candidate; unlocked = true; copied = true; break
                }
            }
        }
        candidates.removeAll()
        if !unlocked {
            if noPrompt { throw Failure.message("Setup required: saved password is missing or no longer unlocks this PDF.") }
            password = try prompt(inputURL.lastPathComponent)
            guard let value = password, pdf.unlock(withPassword: value) else {
                throw Failure.message("Password did not unlock this PDF. No replacement was saved.")
            }
            copied = true
        }
        if copied, let value = password { try savePassword(value, scope) }
        password = nil // Strings/OS libraries cannot promise cryptographic memory erasure.
    }
    guard pdf.pageCount > 0, pdf.pageCount <= 100 else {
        throw Failure.message("PDF must contain 1–100 pages.")
    }
    var pages: [[String: Any]] = []
    for number in 0..<pdf.pageCount {
        guard let page = pdf.page(at: number) else { throw Failure.message("A PDF page could not be read.") }
        pages.append(["page": number + 1, "text": page.string ?? ""])
    }
    let data = try JSONSerialization.data(withJSONObject: ["pages": pages, "page_count": pdf.pageCount, "encrypted": pdf.isEncrypted])
    try data.write(to: outputURL, options: .withoutOverwriting)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: outputURL.path)
    print("Extracted \(pdf.pageCount) page(s) to the private output file.")
}
do { try run() }
catch let Failure.message(message) {
    FileHandle.standardError.write(Data((message + "\n").utf8)); exit(1)
}
catch {
    FileHandle.standardError.write(Data("PDF processing failed. Check the input, output, and local permissions.\n".utf8)); exit(1)
}
