angular.module('aiddataDET')
.controller('LoginCtrl', function($scope, $rootScope, $log, $stateParams, $state, $cookies, ajaxFactory, queryFactory) {

  $scope.requestForm = {
    email: ''
  };
  $scope.requests = [];

  $scope.lookup = function() {
    $state.go('requests', { email: $scope.requestForm.email });
  };

});
