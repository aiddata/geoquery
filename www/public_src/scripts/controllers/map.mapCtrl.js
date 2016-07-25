angular.module('aiddataDET')
.controller('MapCtrl', function($scope, $rootScope, $log, $timeout, mapFactory) {

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision();
    angular.module('DET', ['ngMaterial', 'ngMessages','material.svgAssetsCache'])
    .controller('AppCtrl', function($scope, $mdDialog, $mdMedia) {
      $scope.status = '';
      $scope.customFullscreen = $mdMedia('x') || $mdMedia('sm');

      $scope.showAlert = function(ev) {
        $mdDialog.show()
          $mdDialog.alert()

      .parent(angular.element(document.querySelector('#popupContainer')))
          .clickOutsideToClose(true)
          .title('Welcome to the Data Extraction Tool by AidData!')
          .textContent('This tool aims to influence the spread of aid by allowing users to analyze data based on boundaries, sectors, donors, and other filters.')
          .ariaLabel('Welcome Modal')
          .ok('Click Me!')
          .targetEvent(ev)
        );
      };

      function DialogController ($scope, $mdDialog) {
        $scope.hide = function() {
          $mdDialog.hide();
        };
        $scope.cancel = function() {
          $mdDialog.cancel();
        };
        $scope.answer = function(answer) {
          $mdDialog.hide(answer);
        };
      }
    })

    $timeout(function() { mapFactory.refreshSize(); });
  });

});
