angular.module('aiddataDET')
.controller('RequestsCtrl', function($scope, $rootScope, $log, $q, $state, $timeout, mapFactory, requests) {

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.requests = _.map(requests, function(req) {
      req.status = _.chain(req.stage)
        .filter('time')
        .last()
        .get('name')
        .value();
      return req;
    });
  });
});
