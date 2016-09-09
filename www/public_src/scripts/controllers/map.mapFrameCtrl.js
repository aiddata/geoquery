angular.module('aiddataDET')
.controller('MapFrameCtrl', function($scope, $rootScope, $log, $timeout, $element, mapFactory) {
  $scope.showOverlay = false;

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision(document.querySelector('.map'));
  });

  $scope.$on('mapOverlay:remove', function() {
    $scope.showOverlay = false;
  });

  $scope.$on('mapOverlay:add', function() {
    $scope.showOverlay = true;
  });
});
