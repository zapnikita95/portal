import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:portal_flutter/main.dart';

void main() {
  testWidgets('PortalApp поднимает MaterialApp', (WidgetTester tester) async {
    await tester.pumpWidget(const PortalApp());
    await tester.pump();
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
