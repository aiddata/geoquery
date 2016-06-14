angular.module('aiddataDET')
.controller('ZoomControlsCtrl', function($scope, mapFactory) {
  $scope.zoomIn = mapFactory.zoomIn;
  $scope.zoomOut = mapFactory.zoomOut;
  $scope.resetView = mapFactory.resetView;
});
