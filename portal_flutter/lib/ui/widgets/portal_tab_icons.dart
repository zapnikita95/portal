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
    final scale = size.shortestSide / 24.0;
    final rx = size.width * 0.40;
    final ry = size.height * 0.34;
    final sw = math.max(2.0, 2.4 * scale);

    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = sw
      ..color = color;

    canvas.save();
    canvas.translate(cx, cy);
    canvas.rotate(-0.12);

    final rect = Rect.fromCenter(
      center: Offset.zero,
      width: rx * 2,
      height: ry * 2,
    );
    canvas.drawOval(rect, ring);

    final inner = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = sw * 0.5
      ..color = color.withOpacity(0.5);
    canvas.drawOval(
      Rect.fromCenter(center: Offset.zero, width: rx * 1.38, height: ry * 1.18),
      inner,
    );

    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(1.6, 1.8 * scale)
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..color = color;

    switch (kind) {
      case PortalTabKind.receive:
        // Стрелка вниз к центру (приём)
        canvas.drawLine(Offset(0, -5 * scale), Offset(0, 6 * scale), stroke);
        canvas.drawLine(Offset(-4 * scale, 2 * scale), Offset(0, 6 * scale), stroke);
        canvas.drawLine(Offset(4 * scale, 2 * scale), Offset(0, 6 * scale), stroke);
        break;
      case PortalTabKind.peers:
        final fill = Paint()..style = PaintingStyle.fill..color = color;
        canvas.drawCircle(Offset(-5 * scale, -0.5 * scale), 2.0 * scale, fill);
        canvas.drawCircle(Offset(5 * scale, -0.5 * scale), 2.0 * scale, fill);
        canvas.drawLine(Offset(-2 * scale, 2.5 * scale), Offset(2 * scale, 2.5 * scale), stroke);
        break;
      case PortalTabKind.send:
        // Стрелка вверх от центра (отправка)
        canvas.drawLine(Offset(0, 5 * scale), Offset(0, -6 * scale), stroke);
        canvas.drawLine(Offset(-4 * scale, -2 * scale), Offset(0, -6 * scale), stroke);
        canvas.drawLine(Offset(4 * scale, -2 * scale), Offset(0, -6 * scale), stroke);
        break;
      case PortalTabKind.history:
        final arcRect = Rect.fromCircle(center: Offset.zero, radius: 5.2 * scale);
        canvas.drawArc(
          arcRect,
          -math.pi * 0.05,
          -math.pi * 1.45,
          false,
          stroke,
        );
        const a = -math.pi * 0.05;
        canvas.drawLine(
          Offset(4.8 * scale * math.cos(a), 4.8 * scale * math.sin(a)),
          Offset(6.2 * scale * math.cos(a), 6.2 * scale * math.sin(a)),
          stroke,
        );
        break;
      case PortalTabKind.settings:
        final dot = Paint()..style = PaintingStyle.fill..color = color;
        for (var i = 0; i < 6; i++) {
          final a = i * math.pi / 3 - math.pi / 2;
          final o = Offset(5.2 * scale * math.cos(a), 5.2 * scale * math.sin(a));
          canvas.drawCircle(o, 1.0 * scale, dot);
        }
        final hub = Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = stroke.strokeWidth
          ..color = color;
        canvas.drawCircle(Offset.zero, 2.0 * scale, hub);
        break;
    }

    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _PortalTabPainter oldDelegate) =>
      oldDelegate.kind != kind || oldDelegate.color != color;
}
