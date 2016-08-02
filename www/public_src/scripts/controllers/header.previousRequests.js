angular.module('aiddataDET')
.controller('PreviousRequestsCtrl', function($scope, $rootScope, $log, $stateParams, $state, ajaxFactory) {
  $scope.email = 'eslivinski@gmail.com';

  $scope.lookup = function() {
    ajaxFactory.requests($scope.email)
      .then(function(data) {
        console.log(data);
      }, function(err) {
        console.error(err);
      });
  };

});
