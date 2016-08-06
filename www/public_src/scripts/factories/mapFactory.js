angular.module('aiddataDET')
.factory('mapFactory', function($q, $timeout, $rootScope, ajaxFactory) {

  var map = {};
  var mapboxToken = 'pk.eyJ1IjoiZXNsaXZpbnNraWNhcnRvIiwiYSI6IjRWenpDcmMifQ.IU9qcKhUf_w-lTQQ-I7DIg';

  var defaultView = {
    zoom: 2,
    center: [0, 0]
  };

  var boundaries = {};
  var boundaryGroup = {};

  function retrieveBoundary(boundary) {
    if (boundaries[boundary]) {
      return boundaries[boundary];
    }
    return ajaxFactory.geometry(boundary)
      .then(function(result) {
        if (!result.data) {
          return $q.reject({ message: 'No data returned' });
        }
        console.log(result.data);
        boundaries[boundary] = L.geoJson(result.data);
        return boundaries[boundary];
      }, function(err) {
        /* @TODO: Create error messaging */
        console.error(err);
        return $q.reject(err);
      });
  }

  return {
    provision: function(element, locked, callback) {
      var promise = $q.defer();
      /* Basemap */
      var basemap = L.tileLayer('https://api.mapbox.com/styles/v1/mapbox/emerald-v8/tiles/{z}/{x}/{y}?access_token=' + mapboxToken, {
        attribution: '© <a href="https://www.mapbox.com/map-feedback/">Mapbox</a> © <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      });
      basemap.once('load', function() {
        map.invalidateSize().resetView();
        return promise.resolve(map);
      });

      /* Boundary Group */
      boundaryGroup = L.featureGroup()
        .on('layeradd', function() {
          this.setStyle({ opacity: 0, fillOpacity: 0 });
          map.fitBounds(this);
          // Delaying restyle allows for animations
          $timeout(function() {
            boundaryGroup.setStyle({ opacity: 0.5, fillOpacity: 0.2 });
          }, 600);
        });

      /* Map */
      map = L.map(element, {
        zoomControl: false,
        layers: [ basemap, boundaryGroup ],
        doubleClickZoom: false,
        zoomAnimation: true,
        zoomAnimationThreshold: 20,
        trackResize: true,
        dragging: !locked,
        boxZoom: !locked,
        scrollWheelZoom: !locked
      });

      map.resetView = function() { this.setView(defaultView.center, defaultView.zoom); };
      map.resetView();
      return promise;
    },

    zoomIn: function() {
      map.zoomIn();
    },

    zoomOut: function() {
      map.zoomOut();
    },

    resetView: function() {
      $rootScope.$broadcast('mapOverlay:add');
      map.resetView();
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

      $q.when(retrieveBoundary(boundary))
        .then(function(layer) {
          // factory.clearBoundaries();
          boundaryGroup.addLayer(layer);
        })
        .finally(function() {
          $rootScope.$broadcast('mapOverlay:remove');
          factory.stopSpin();
        });
    },

    clearBoundaries: function () {
      boundaryGroup.clearLayers();
    }
  };
});
