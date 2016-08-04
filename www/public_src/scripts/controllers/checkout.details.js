angular.module('aiddataDET')
.controller('DetailsCtrl', function($scope, $rootScope, $log, $q, $timeout, $state, $element, $mdDialog, queryFactory, mapFactory, spinFactory) {
  $scope.queryObj = queryFactory.getQuery();
  $scope.queryData = {
    email: '',
    custom_name: 'Unamed Request'
  };

  var submitAlert = $mdDialog.confirm()
      .clickOutsideToClose(true)
      .title("Your Request Has been Submitted!")
      .ok('Review Request Status')
      .cancel('Start New Search');

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
    var id;

    spinFactory.start();

    queryFactory.submitRequest($scope.queryData)
      .then(function(data) {
        spinFactory.stop();
        id = data.request._id.$id;
        return $mdDialog.show(submitAlert);
      })
      .then(function() {
        return $state.go('status', { id: id });
      })
      .catch(function (err) {
        $log.error(err);
        return $state.go('map');
      })
      .finally(function() {
        /* This Reset Call is Not Working */
        queryFactory.resetQuery();
      });
  };

  $scope.addRequest = function () {
    $state.go('search', {
      boundary: queryFactory.getBoundary().boundaryId,
      subboundary: queryFactory.getSubBoundary().name
    });
  };

  $scope.$on('$viewContentLoaded', function() {
    mapFactory.provision(document.querySelector('.map'), true);
    var sub = queryFactory.getSubBoundary().name;
    mapFactory.mapBoundary(sub);
  });

});
