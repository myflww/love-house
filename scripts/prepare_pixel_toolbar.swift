// Standard asset preparation only: crop approved imagegen atlas pixels; never redraw them.
import AppKit
import Foundation

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let sourceURL = root.appendingPathComponent("assets/ui/pixel-icons-generated.png")
let outputURL = root.appendingPathComponent("assets/ui/toolbar-icons", isDirectory: true)
guard let data = try? Data(contentsOf: sourceURL),
      let bitmap = NSBitmapImageRep(data: data), let source = bitmap.cgImage else {
    fatalError("Approved imagegen atlas is unavailable")
}
try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)
let columns = 5, rows = 4
let mapping = [("fit", 0, 3), ("refresh", 4, 1), ("files", 1, 3)]
var manifest: [String: Any] = ["source": "assets/ui/pixel-icons-generated.png", "width": source.width, "height": source.height,
                              "columns": columns, "rows": rows, "operation": "crop only, original pixels preserved"]
var crops: [String: Any] = [:]
for (name, column, row) in mapping {
    let cellX = Int((Double(column) * Double(source.width) / Double(columns)).rounded())
    let cellY = Int((Double(row) * Double(source.height) / Double(rows)).rounded())
    let cellRight = Int((Double(column + 1) * Double(source.width) / Double(columns)).rounded())
    let cellBottom = Int((Double(row + 1) * Double(source.height) / Double(rows)).rounded())
    var minX = cellRight, minY = cellBottom, maxX = cellX, maxY = cellY
    // Only locate the existing dark cocoa outline against the cream canvas.
    for y in cellY..<cellBottom {
        for x in cellX..<cellRight {
            guard let c = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else { continue }
            if c.redComponent < 0.59 && c.greenComponent < 0.52 && c.blueComponent < 0.48 {
                minX = min(minX, x); minY = min(minY, y); maxX = max(maxX, x); maxY = max(maxY, y)
            }
        }
    }
    guard maxX >= minX && maxY >= minY else { fatalError("Atlas cell lacks a visible icon: \(name)") }
    let side = min(max(maxX - minX + 1, maxY - minY + 1) + 20, min(cellRight - cellX, cellBottom - cellY))
    let x = max(cellX, min((minX + maxX + 1 - side) / 2, cellRight - side))
    let y = max(cellY, min((minY + maxY + 1 - side) / 2, cellBottom - side))
    guard let cropped = source.cropping(to: CGRect(x: x, y: y, width: side, height: side)),
          let png = NSBitmapImageRep(cgImage: cropped).representation(using: .png, properties: [:]) else {
        fatalError("Cannot encode \(name) crop")
    }
    try png.write(to: outputURL.appendingPathComponent(name + ".png"), options: .atomic)
    crops[name] = ["column": column, "row": row, "rect": [x, y, side, side], "size": side]
}
manifest["crops"] = crops
let json = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
try json.write(to: outputURL.appendingPathComponent("crop-provenance.json"), options: .atomic)
print(String(data: json, encoding: .utf8)!)
