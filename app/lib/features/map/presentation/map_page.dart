import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

class MapPage extends StatelessWidget {
  const MapPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('GeoPTT - Mapa')),
      body: FlutterMap(
        options: MapOptions(
          initialCenter: LatLng(-23.9608, -46.3331), // Santos
          initialZoom: 15,
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            subdomains: const ['a', 'b', 'c'],
            userAgentPackageName: 'com.geoptt',
          ),
          MarkerLayer(
            markers: [
              Marker(
                point: LatLng(-23.9608, -46.3331),
                width: 60,
                height: 60,
                child: const Icon(Icons.person_pin_circle, size: 40, color: Colors.blue),
              ),
            ],
          ),
        ],
      ),
    );
  }
}