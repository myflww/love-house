import AppKit

let output = CommandLine.arguments[1]
let size = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
NSColor(calibratedRed: 0.055, green: 0.15, blue: 0.13, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: size, height: size), xRadius: 218, yRadius: 218).fill()
let gold = NSColor(calibratedRed: 0.91, green: 0.79, blue: 0.47, alpha: 1)
let mint = NSColor(calibratedRed: 0.52, green: 0.82, blue: 0.72, alpha: 1)
var points: [NSPoint] = [NSPoint(x: 512, y: 512)]
for i in 0..<36 {
    let angle = Double(i) * 2.39996323
    let radius = 90.0 + sqrt(Double(i) / 35.0) * 290.0
    points.append(NSPoint(x: 512 + cos(angle) * radius, y: 512 + sin(angle) * radius))
}
for i in 1..<points.count {
    for j in max(0, i - 4)..<i {
        mint.withAlphaComponent(0.22).setStroke()
        let edge = NSBezierPath()
        edge.lineWidth = 2.4
        edge.move(to: points[i])
        edge.line(to: points[j])
        edge.stroke()
    }
}
for (i, p) in points.enumerated() {
    let radius = i == 0 ? 25.0 : i % 7 == 0 ? 12.0 : 6.5
    (i % 5 == 0 ? gold : mint).setFill()
    NSBezierPath(ovalIn: NSRect(x: p.x - radius, y: p.y - radius,
                              width: radius * 2, height: radius * 2)).fill()
}
gold.setStroke()
let orbit = NSBezierPath(ovalIn: NSRect(x: 113, y: 113, width: 798, height: 798))
orbit.lineWidth = 2
orbit.stroke()
image.unlockFocus()
guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else { fatalError("icon render failed") }
try png.write(to: URL(fileURLWithPath: output))
