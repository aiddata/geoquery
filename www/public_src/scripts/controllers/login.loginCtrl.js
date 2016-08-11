angular.module('aiddataDET')
.controller('LoginCtrl', function($scope, $rootScope, $log, $stateParams, $state, ajaxFactory, queryFactory) {

  $scope.requestForm = {
    email: ''
  };
  $scope.requests = [];

  $scope.lookup = function() {
    $state.go('requests', { email: $scope.requestForm.email });
  };

});
