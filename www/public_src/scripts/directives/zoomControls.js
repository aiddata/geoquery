angular.module('aiddataDET')
.directive('zoomControls', function($window) {
  return {
    restrict: "E",
    controller: 'ZoomControlsCtrl',
    scope: { },
    link:  { },
    templateUrl: "views/components/zoomControls.html"
  };
});
