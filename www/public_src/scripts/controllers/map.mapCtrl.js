angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, mapFactory) {
  $scope.showOverlay = false;

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision();

    $timeout(function() { mapFactory.refreshSize(); });
  });

  $scope.$on('mapOverlay:remove', function() {
    $scope.showOverlay = false;
  });

  $scope.$on('mapOverlay:add', function() {
    $scope.showOverlay = true;
  });

});
