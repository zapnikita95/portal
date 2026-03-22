import 'dart:math' as math;
import 'package:flutter/material.dart';

/// Стиль навигации в духе виджета Portal (фиолетовое «кольцо» / овал).
enum PortalTabKind { receive, peers, send, history, settings }

class PortalTabIcon extends StatelessWidget {
  const PortalTabIcon({
    super.key,
    required this.kind,
    required this.selected,
    this.size = 24,
  });

  final PortalTabKind kind;
  final bool selected;
  final double size;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final c = selected ? cs.primary : cs.onSurfaceVariant;
    return CustomPaint(
      size: Size(size, size),
      painter: _PortalTabPainter(kind: kind, color: c),
    );
  }
}

class _PortalTabPainter extends CustomPainter {
  _PortalTabPainter({required this.kind, required this.color});

  final PortalTabKind kind;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final rx = size.width * 0.42;
    final ry = size.height * 0.36;
    final sw = math.max(2.0, size.shortestSide * 0.12);

    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = sw
      ..color = color;

    canvas.save();
    canvas.translate(cx, cy);
    canvas.rotate(-0.15);

    final rect = Rect.fromCenter(
      center: Offset.zero,
      width: rx * 2,
      height: ry * 2,
    );
    canvas.drawOval(rect, ring);

    final inner = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = sw * 0.55
      ..color = color.withValues(alpha: 0.55);
    canvas.drawOval(
      Rect.fromCenter(center: Offset.zero, width: rx * 1.35, height: ry * 1.2),
      inner,
    );

    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(1.5, size.shortestSide * 0.08)
      ..strokeCap = StrokeCap.round
      ..color = color;

    switch (kind) {
      case PortalTabKind.receive:
        canvas.drawLine(const Offset(-1, 2), const Offset(-1, 7), stroke);
        canvas.drawLine(const Offset(-4, 5), const Offset(-1, 7), stroke);
        canvas.drawLine(const Offset(2, 5), const Offset(-1, 7), stroke);
        break;
      case PortalTabKind.peers:
        final fill = Paint()..style = PaintingStyle.fill..color = color;
        canvas.drawCircle(const Offset(-5, -1), 2.2, fill);
        canvas.drawCircle(const Offset(5, -1), 2.2, fill);
        canvas.drawLine(const Offset(-2.5, 1), const Offset(2.5, 1), stroke);
        break;
      case PortalTabKind.send:
        canvas.drawLine(const Offset(-1, -2), const Offset(-1, -7), stroke);
        canvas.drawLine(const Offset(-4, -5), const Offset(-1, -7), stroke);
        canvas.drawLine(const Offset(2, -5), const Offset(-1, -7), stroke);
        break;
      case PortalTabKind.history:
        canvas.drawArc(
          Rect.fromCircle(center: Offset.zero, radius: 5),
          -math.pi * 0.1,
          -math.pi * 1.3,
          false,
          stroke,
        );
        final a = -math.pi * 0.1;
        canvas.drawLine(
          Offset(3 * math.cos(a), 3 * math.sin(a)),
          Offset(5 * math.cos(a), 5 * math.sin(a)),
          stroke,
        );
        break;
      case PortalTabKind.settings:
        final dot = Paint()..style = PaintingStyle.fill..color = color;
        for (var i = 0; i < 6; i++) {
          final a = i * math.pi / 3;
          final o = Offset(5.5 * math.cos(a), 5.5 * math.sin(a));
          canvas.drawCircle(o, 1.1, dot);
        }
        final hub = Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = stroke.strokeWidth
          ..color = color;
        canvas.drawCircle(Offset.zero, 2.2, hub);
        break;
    }

    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _PortalTabPainter oldDelegate) =>
      oldDelegate.kind != kind || oldDelegate.color != color;
}
