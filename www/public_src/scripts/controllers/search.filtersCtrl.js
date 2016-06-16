angular.module('aiddataDET')
.controller('FiltersCtrl', function($scope, $rootScope, $stateParams, $q, ajaxFactory) {
  $scope.filters = { };
  $scope.searchData = { };

  $scope.filterInfo = {
    'ad_sector_names': { text: 'Sectors', type: 'options' },
    'donors': { text: 'Donors', type: 'options' },
    'years': { text: 'Years', type: 'range' }
  };

  $scope.updateFilters = function () {
    ajaxFactory.filters($scope.filters)
      .then(function(results) {
        console.log(results.data);
        $scope.searchData = results.data;
        $scope.searchData.filterTypes = _.keys($scope.searchData.distinct);

      }, function(err) {
        console.log(err);
      });
  };

  $scope.toggleFilter = function (filter, value, dir) {
    if (dir === true) {
      if (!$scope.filters[filter]) {
        $scope.filters[filter] = [];
      }
      $scope.filters[filter].push(value);
    }
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    _.extend($scope.filters, data);
    $scope.updateFilters();
  });


});
