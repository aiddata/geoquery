angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, mapFactory, $mdDialog) {
  $scope.showOverlay = false;

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision();
    showAlert();
  });

  function showAlert() {
    $mdDialog.show(
      $mdDialog.alert()
      .parent(angular.element(document.querySelector('body')))
      .clickOutsideToClose(true)
      .title("Welcome to the Data Extraction Tool by AidData!")
      .textContent('Allowing YOU to extend a helping hand...')
      .ok('Get Started')
    );
  }

  $scope.$on('mapOverlay:remove', function() {
    $scope.showOverlay = false;
  });

  $scope.$on('mapOverlay:add', function() {
    $scope.showOverlay = true;
  });
});
