angular.module('aiddataDET')
.factory('mapFactory', function() {

  var map = {};

  return {
    provision: function() {
      map = L.map('map').setView([0, 0], 2);

      var mapboxToken = 'pk.eyJ1IjoiZXNsaXZpbnNraWNhcnRvIiwiYSI6IjRWenpDcmMifQ.IU9qcKhUf_w-lTQQ-I7DIg';
      L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/emerald-v8/tiles/{z}/{x}/{y}?access_token=' + mapboxToken, {
        attribution: '© <a href="https://www.mapbox.com/map-feedback/">Mapbox</a> © <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(map);
    },

    refreshSize: function () {
      map.invalidateSize();
    }
  };
});
