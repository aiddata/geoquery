angular.module('aiddataDET')
.controller('PreviousRequestsCtrl', function($scope, $rootScope, $log, $stateParams, $state, ajaxFactory, queryFactory) {

  $scope.email = 'eslivinski@gmail.com';
  $scope.requests = [];

  $scope.lookup = function() {
    ajaxFactory.requests('email', $scope.email)
      .then(function(results) {
        $scope.requests = results.data;
      }, function(err) {
        console.error(err);
      });
  };

  $scope.viewStatus = function (id) {
    var url = $state.href('status', { 'id': id });
    window.open(url, '_blank');
  };

  $scope.getStage = function(req) {
    return _.chain(req)
    .get('stage')
    .each(function(stage) {
      stage.timeFormat = Date(req);
      console.log(stage.timeFormat);
    })
    .filter('time')
    .last()
    .value();
  };

});
