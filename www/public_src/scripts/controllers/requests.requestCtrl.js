angular.module('aiddataDET')
.controller('RequestsCtrl', function($scope, $rootScope, $log, $q, $state, $stateParams, $timeout, queryFactory, requests) {

  $scope.email = $stateParams.email;

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.requests = _.map(requests, function(req) {
      req.status = _.chain(req.stage)
        .filter('time')
        .each(function(stage) {
          stage.time_ms = stage.time * 1000;
          stage.time_format = queryFactory.getTimeStamp(stage.time_ms);
        })
        .last()
        .get('name')
        .value();
      req.submissionTime = _.get(_.head(req.stage), 'time_format') || '';
      return req;
    });
  });
});
