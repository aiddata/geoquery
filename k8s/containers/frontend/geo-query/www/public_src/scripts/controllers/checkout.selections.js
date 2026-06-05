angular.module('aiddataDET')
.controller('SelectionsCtrl', function($scope, $rootScope, $log, $stateParams, $state, $mdDialog, queryFactory, modalFactory, modals) {
  $scope.queryObj = queryFactory.getQuery();
  var emptyRequest = modalFactory.confirm(modals.emptyRequest);

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.removeQuery = function (q, type) {
    if ($scope.queryObj.raster_data.length + $scope.queryObj.release_data.length === 1) {
      return $mdDialog.show(emptyRequest)
        .then(function() { deleteRequest(q, type); })
        .then($scope.addRequest);
    }
    deleteRequest(q, type);
  };

  $scope.addRequest = function () {
    $state.go('search', {
      boundary: queryFactory.getBoundary().boundaryId,
      subboundary: queryFactory.getSubBoundary().name
    });
  };


  function deleteRequest (q, type) {
    return queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  }

});
