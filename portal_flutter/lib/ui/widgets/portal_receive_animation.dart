import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Пресеты анимации на экране «Приём» (настройка `portal_anim` в JSON).
class PortalReceiveAnimation extends StatefulWidget {
  const PortalReceiveAnimation({
    super.key,
    required this.active,
    required this.preset,
    this.size = 140,
  });

  final bool active;
  final String preset;
  final double size;

  @override
  State<PortalReceiveAnimation> createState() => _PortalReceiveAnimationState();
}

class _PortalReceiveAnimationState extends State<PortalReceiveAnimation>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..repeat();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final p = widget.preset.trim().toLowerCase();
    final useGif = p == 'branding' || p == 'gif' || p == 'portal_main';
    if (useGif) {
      final img = Image.asset(
        'assets/portal_main.gif',
        width: widget.size,
        height: widget.size,
        fit: BoxFit.contain,
        gaplessPlayback: true,
        errorBuilder: (_, __, ___) =>
            _StaticPortal(size: widget.size, color: cs.primary),
      );
      if (!widget.active) {
        return Opacity(
          opacity: 0.4,
          child: ColorFiltered(
            colorFilter: const ColorFilter.matrix(<double>[
              0.2126, 0.7152, 0.0722, 0, 0,
              0.2126, 0.7152, 0.0722, 0, 0,
              0.2126, 0.7152, 0.0722, 0, 0,
              0, 0, 0, 1, 0,
            ]),
            child: img,
          ),
        );
      }
      return img;
    }
    if (!widget.active || p == 'static' || p == 'calm') {
      return _StaticPortal(size: widget.size, color: cs.primary);
    }
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final t = _c.value;
        if (p == 'rings' || p == 'orbit') {
          return CustomPaint(
            size: Size(widget.size, widget.size),
            painter: _RingsPainter(
              color: cs.primary,
              t: t,
            ),
          );
        }
        // default: pulse / breathe
        final scale = 0.88 + 0.12 * math.sin(t * math.pi * 2);
        final glow = 0.35 + 0.25 * math.sin(t * math.pi * 2 + 0.5);
        return Transform.scale(
          scale: scale,
          child: CustomPaint(
            size: Size(widget.size, widget.size),
            painter: _StaticPortalPainter(
              color: cs.primary,
              glow: glow,
            ),
          ),
        );
      },
    );
  }
}

class _StaticPortal extends StatelessWidget {
  const _StaticPortal({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: Size(size, size),
      painter: _StaticPortalPainter(color: color, glow: 0.45),
    );
  }
}

class _StaticPortalPainter extends CustomPainter {
  _StaticPortalPainter({required this.color, required this.glow});

  final Color color;
  final double glow;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final rx = size.width * 0.38;
    final ry = size.height * 0.32;

    final bg = Paint()
      ..shader = RadialGradient(
        colors: [
          color.withOpacity(0.15 + glow * 0.2),
          color.withOpacity(0.02),
        ],
      ).createShader(Rect.fromCircle(center: Offset(cx, cy), radius: size.shortestSide * 0.55));

    canvas.drawCircle(Offset(cx, cy), size.shortestSide * 0.48, bg);

    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(3.0, size.shortestSide * 0.06)
      ..color = color;

    canvas.save();
    canvas.translate(cx, cy);
    canvas.rotate(-0.18);
    canvas.drawOval(
      Rect.fromCenter(center: Offset.zero, width: rx * 2, height: ry * 2),
      ring,
    );
    final inner = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = ring.strokeWidth * 0.5
      ..color = color.withOpacity(0.5);
    canvas.drawOval(
      Rect.fromCenter(center: Offset.zero, width: rx * 1.45, height: ry * 1.25),
      inner,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _StaticPortalPainter oldDelegate) =>
      oldDelegate.color != color || oldDelegate.glow != glow;
}

class _RingsPainter extends CustomPainter {
  _RingsPainter({required this.color, required this.t});

  final Color color;
  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(2.5, size.shortestSide * 0.045)
      ..color = color.withOpacity(0.85);

    canvas.save();
    canvas.translate(cx, cy);
    for (var i = 0; i < 3; i++) {
      final rot = (t + i * 0.33) * math.pi * 2;
      canvas.save();
      canvas.rotate(rot * (i.isEven ? 1 : -1));
      final s = 0.65 + i * 0.12;
      final ringPaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = paint.strokeWidth
        ..color = color.withOpacity((0.55 - i * 0.12).clamp(0.12, 1.0));
      canvas.drawOval(
        Rect.fromCenter(
          center: Offset.zero,
          width: size.width * 0.5 * s,
          height: size.height * 0.42 * s,
        ),
        ringPaint,
      );
      canvas.restore();
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _RingsPainter oldDelegate) =>
      oldDelegate.t != t || oldDelegate.color != color;
}
