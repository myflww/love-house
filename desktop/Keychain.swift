import Foundation
import Security
import LocalAuthentication

// New namespace only. Neither the service nor an access group is caller-controlled.
private let service = "local.neural-knowledge.ai-credentials.v1"
private let maxInput = 65536

private func reply(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
}

private func fail(_ code: String, status: OSStatus? = nil) {
    var value: [String: Any] = ["ok": false, "error": code]
    if let status = status { value["status"] = Int(status) }
    reply(value)
}

let input = FileHandle.standardInput.readData(ofLength: maxInput + 1)
if input.count > maxInput {
    fail("request_too_large")
} else if let object = try? JSONSerialization.jsonObject(with: input),
          let request = object as? [String: Any],
          let operation = request["op"] as? String,
          let account = request["account"] as? String,
          account.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
          Set(request.keys).isSubset(of: ["op", "account", "value"]) {
    let authentication = LAContext()
    authentication.interactionNotAllowed = true
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service,
        kSecAttrAccount as String: account,
        kSecUseAuthenticationContext as String: authentication
    ]
    switch operation {
    case "set":
        if let value = request["value"] as? String, !value.isEmpty,
           let bytes = value.data(using: .utf8), bytes.count <= 32768 {
            let changes = [kSecValueData as String: bytes]
            var status = SecItemUpdate(query as CFDictionary, changes as CFDictionary)
            if status == errSecItemNotFound {
                var item = query
                item[kSecValueData as String] = bytes
                item[kSecAttrLabel as String] = "爱之屋 · 本机连接凭据"
                status = SecItemAdd(item as CFDictionary, nil)
            }
            if status == errSecSuccess { reply(["ok": true, "storage": "keychain"]) }
            else { fail("keychain_write_failed", status: status) }
        } else { fail("invalid_value") }
    case "get":
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { reply(["ok": true, "found": false]) }
        else if status == errSecSuccess, let data = result as? Data,
                let value = String(data: data, encoding: .utf8) {
            // This value is for the private parent pipe only. Never log or expose it in UI metadata.
            reply(["ok": true, "found": true, "value": value, "storage": "keychain"])
        } else { fail("keychain_read_failed", status: status) }
    case "delete":
        let status = SecItemDelete(query as CFDictionary)
        if status == errSecSuccess || status == errSecItemNotFound { reply(["ok": true]) }
        else { fail("keychain_delete_failed", status: status) }
    default: fail("invalid_operation")
    }
} else {
    fail("invalid_request")
}
