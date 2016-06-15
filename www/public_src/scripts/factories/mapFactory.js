angular.module('aiddataDET')
.factory('mapFactory', function($q, ajaxFactory) {

  var map = {};
  var mapboxToken = 'pk.eyJ1IjoiZXNsaXZpbnNraWNhcnRvIiwiYSI6IjRWenpDcmMifQ.IU9qcKhUf_w-lTQQ-I7DIg';

  var boundaries = {};
  var boundaryGroup = {};

  function retrieveBoundary(boundary) {
    if (boundaries[boundary]) {
      return $q.when(function() { return boundaries[boundary]; });
    }
    return ajaxFactory.geometry(boundary)
      .then(function(result) {
        boundaries[boundary] = L.geoJson(result.data);
        return boundaries[boundary];
      });
  }

  return {
    provision: function() {
      /* Map */
      map = L.map('map', {
        zoomControl: false
      }).setView([0, 0], 2);

      /* Basemap */
      L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/emerald-v8/tiles/{z}/{x}/{y}?access_token=' + mapboxToken, {
        attribution: '© <a href="https://www.mapbox.com/map-feedback/">Mapbox</a> © <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(map);

      /* Boundary Group */
      boundaryGroup = L.featureGroup();
      boundaryGroup.on('layeradd', function(e) { map.fitBounds(this); });
      boundaryGroup.addTo(map);
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

    mapBoundary: function (boundary) {
      var factory = this;
      retrieveBoundary(boundary)
        .then(function(layer) {
          factory.clearBoundaries();
          boundaryGroup.addLayer(layer);
        });
    },

    clearBoundaries: function () {
      boundaryGroup.clearLayers();
    }
  };
});
