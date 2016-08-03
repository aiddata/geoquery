angular.module('aiddataDET')
.controller('RequestsCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.queryObj = queryFactory.getQuery();

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.removeQuery = function (q, type) {
    queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };

  $scope.submitQuery = function () {
    var email = 'eslivinski@gmail.com';
    queryFactory.submitRequest(email)
      .then(function(data) {
        console.log('It Worked', data);
      }, function (err) {
        console.error('It didnt work', err);
      });
  };

  $scope.addRequest = function () {
    $state.go('search', {
      boundary: queryFactory.getBoundary().boundaryId,
      subboundary: queryFactory.getSubBoundary().name
    });
  };

});
