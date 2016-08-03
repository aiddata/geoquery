angular.module('aiddataDET')
.controller('DetailsCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory, mapFactory) {
  $scope.queryObj = queryFactory.getQuery();
  $scope.queryData = {
    email: '',
    custom_name: 'Unamed Request'
  };

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
    queryFactory.submitRequest($scope.queryData.email)
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

  $scope.$on('$viewContentLoaded', function(event) {
    mapFactory.provision();

  });

});
