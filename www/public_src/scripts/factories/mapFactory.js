angular.module('aiddataDET')
.factory('mapFactory', function($q, $timeout, ajaxFactory) {

  var map = {};
  var mapboxToken = 'pk.eyJ1IjoiZXNsaXZpbnNraWNhcnRvIiwiYSI6IjRWenpDcmMifQ.IU9qcKhUf_w-lTQQ-I7DIg';

  var boundaries = {};
  var boundaryGroup = {};

  function retrieveBoundary(boundary) {
    if (boundaries[boundary]) {
      $q.when(function() { return boundaries[boundary]; });
    }
    return ajaxFactory.geometry(boundary)
      .then(function(result) {
        boundaries[boundary] = L.geoJson(result.data);
        return boundaries[boundary];
      });
  }

  return {
    provision: function() {
      /* Basemap */
      var basemap = L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/emerald-v8/tiles/{z}/{x}/{y}?access_token=' + mapboxToken, {
        attribution: '© <a href="https://www.mapbox.com/map-feedback/">Mapbox</a> © <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      });

      /* Boundary Group */
      boundaryGroup = L.featureGroup()
        .on('layeradd', function(e) {
          this.setStyle({ opacity: 0, fillOpacity: 0 });
          map.fitBounds(this);
          // Delaying restyle allows for 'animate inå'
          $timeout(function() {
            boundaryGroup.setStyle({ opacity: 0.5, fillOpacity: 0.2 });
          }, 600);
        });

      /* Map */
      map = L.map('map', {
        zoomControl: false,
        layers: [basemap, boundaryGroup],
        zoom: 2,
        center: [0, 0],
        doubleClickZoom: false,
        zoomAnimation: true,
        zoomAnimationThreshold: 20
      });
    },

    refreshSize: function () {
      map.invalidateSize();
    },

    zoomIn: function() {
      map.zoomIn();
    },

    zoomOut: function() {
      map.zoomOut();
    },

    resetView: function() {
      map.setView([0, 0], 2);
    },

    startSpin: function() {
      map.spin(true, { color: '#fff' });
    },

    stopSpin: function() {
      map.spin(false);
    },

    mapBoundary: function (boundary) {
      var factory = this;
      factory.startSpin();

      retrieveBoundary(boundary)
        .then(function(layer) {
          factory.clearBoundaries();
          boundaryGroup.addLayer(layer);
        })
        .finally(function() {
          factory.stopSpin();
        });
    },

    clearBoundaries: function () {
      boundaryGroup.clearLayers();
    }
  };
});
