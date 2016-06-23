angular.module('aiddataDET')
.directive('datasetSelector', function($window) {
  return {
    restrict: "E",
    controller: 'DatasetSelectorCtrl',
    scope: { },
    link:  {
      post : function(scope){
        // Handle All resize events, and adjust the map size as necessary
        scope.getWindowDimensions = function() {
          return { 'h': $window.innerHeight };
        };

        scope.$watch(scope.getWindowDimensions, function(newValue) {
          /* @TODO: Remove hardcoded headerHeight value */
          var headerHeight = 80;
          scope.dataStyle = {
            'height': newValue.h - headerHeight + 'px'
          };
        }, true);

        angular.element($window).bind('resize', function () {
          scope.$apply();
        });

      }
    },
    templateUrl: "views/components/search-datasetSelector.html"
  };
});
