angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, $element, mapFactory, $mdDialog) {
  $scope.showOverlay = false;

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision(document.querySelector('.map.searchMap'));
  });

  $scope.$on('mapOverlay:remove', function() {
    $scope.showOverlay = false;
  });

  $scope.$on('mapOverlay:add', function() {
    $scope.showOverlay = true;
  });
});
