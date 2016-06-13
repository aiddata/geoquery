angular.module('aiddataDET')
.directive('detMap', function($window) {
  return {
    restrict: "E",
    controller: 'MapCtrl',
    scope: { },
    link:  {
      post : function(scope){

        // Handle All resize events, and adjust the map size as necessary
        scope.getWindowDimensions = function() {
          // Be sure this runs here, otherwise Leaflet won't handle the initial resize well
          scope.refreshMapSize();
          return { 'h': $window.innerHeight, 'w': $window.innerWidth };
        };

        scope.$watch(scope.getWindowDimensions, function(newValue) {
          scope.mapStyle = {
            'height': newValue.h + 'px',
            'width': newValue.w + 'px'
          };
        }, true);

        angular.element($window).bind('resize', function () {
          scope.$apply();
        });

      }

    },
    template: "<div id='map' ng-style='mapStyle'></div>"
  };
});
