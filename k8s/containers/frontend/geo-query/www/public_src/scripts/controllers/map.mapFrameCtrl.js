angular.module('aiddataDET')
.controller('MapFrameCtrl', function($scope, $rootScope, $log, $timeout, $element, mapFactory, info) {
  $scope.showOverlay = false;


  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision(document.querySelector('.map'));
    $timeout(function() {
      $scope.overlayText = _.isNil(info.boundary_selection_intro) ? 'Select a boundary of the left to begin' :
        info.boundary_selection_intro;
    }, 1200);
  });

  $scope.$on('mapOverlay:remove', function() {
    $scope.showOverlay = false;
  });

  $scope.$on('mapOverlay:add', function() {
    $scope.showOverlay = true;
  });
});
